from itertools import chain

from flask import current_app, jsonify, request
from notifications_utils.polygons import Polygons
from notifications_utils.template import BroadcastMessageTemplate
from sqlalchemy.orm.exc import MultipleResultsFound

from app import api_user, authenticated_service, redis_store
from app.broadcast_message.translators import cap_xml_to_dict
from app.broadcast_message.utils import (
    validate_and_update_broadcast_message_status,
)
from app.dao.broadcast_message_dao import (
    dao_get_broadcast_message_by_references_and_service_id,
)
from app.dao.dao_utils import dao_save_object
from app.models import BROADCAST_TYPE, BroadcastMessage, BroadcastStatusType
from app.notifications.validators import check_service_has_permission
from app.schema_validation import validate
from app.v2.broadcast import v2_broadcast_blueprint
from app.v2.broadcast.broadcast_schemas import post_broadcast_schema
from app.v2.errors import BadRequestError, ValidationError
from app.xml_schemas import validate_xml


@v2_broadcast_blueprint.route("", methods=['POST'])
def create_broadcast():

    check_service_has_permission(
        BROADCAST_TYPE,
        authenticated_service.permissions,
    )

    if request.content_type != 'application/cap+xml':
        raise BadRequestError(
            message=f'Content type {request.content_type} not supported',
            status_code=415,
        )

    cap_xml = request.get_data()

    if not validate_xml(cap_xml, 'CAP-v1.2.xsd'):
        raise BadRequestError(
            message='Request data is not valid CAP XML',
            status_code=400,
        )
    broadcast_json = cap_xml_to_dict(cap_xml)

    validate(broadcast_json, post_broadcast_schema)

    if broadcast_json["msgType"] == "Cancel":
        if broadcast_json["references"] is None:
            raise BadRequestError(
                message='Missing <references>',
                status_code=400,
            )
        broadcast_message = _cancel_or_reject_broadcast(
            broadcast_json["references"].split(","),
            authenticated_service.id
        )
        return jsonify(broadcast_message.serialize()), 201

    else:
        _validate_template(broadcast_json)

        polygons = Polygons(list(chain.from_iterable((
            [
                [[y, x] for x, y in polygon]
                for polygon in area['polygons']
            ] for area in broadcast_json['areas']
        ))))

        if len(polygons) > 12 or polygons.point_count > 250:
            simple_polygons = polygons.smooth.simplify
        else:
            simple_polygons = polygons

        broadcast_message = BroadcastMessage(
            service_id=authenticated_service.id,
            content=broadcast_json['content'],
            reference=broadcast_json['reference'],
            cap_event=broadcast_json['cap_event'],
            areas={
                'names': [
                    area['name'] for area in broadcast_json['areas']
                ],
                'simple_polygons': simple_polygons.as_coordinate_pairs_lat_long,
            },
            status=BroadcastStatusType.PENDING_APPROVAL,
            created_by_api_key_id=api_user.id,
            stubbed=authenticated_service.restricted
            # The client may pass in broadcast_json['expires'] but it’s
            # simpler for now to ignore it and have the rules around expiry
            # for broadcasts created with the API match those created from
            # the admin app
        )

        dao_save_object(broadcast_message)

        current_app.logger.info(
            f'Broadcast message {broadcast_message.id} created for service '
            f'{authenticated_service.id} with reference {broadcast_json["reference"]}'
        )

        return jsonify(broadcast_message.serialize()), 201


def _cancel_or_reject_broadcast(references_to_original_broadcast, service_id):
    try:
        broadcast_message = dao_get_broadcast_message_by_references_and_service_id(
            references_to_original_broadcast,
            service_id
        )
    except MultipleResultsFound:
        raise BadRequestError(
            message='Multiple alerts found - unclear which one to cancel',
            status_code=400,
        )

    if broadcast_message.status == BroadcastStatusType.PENDING_APPROVAL:
        new_status = BroadcastStatusType.REJECTED
    else:
        new_status = BroadcastStatusType.CANCELLED
    validate_and_update_broadcast_message_status(
        broadcast_message,
        new_status,
        api_key_id=api_user.id
    )
    redis_store.delete(
        f'service-{broadcast_message.service_id}-broadcast-message-{broadcast_message.id}'
    )
    return broadcast_message


def _validate_template(broadcast_json):
    template = BroadcastMessageTemplate.from_content(
        broadcast_json['content']
    )

    if template.content_too_long:
        raise ValidationError(
            message=(
                f'description must be {template.max_content_count:,.0f} '
                f'characters or fewer'
            ) + (
                ' (because it could not be GSM7 encoded)'
                if template.non_gsm_characters else ''
            ),
            status_code=400,
        )
