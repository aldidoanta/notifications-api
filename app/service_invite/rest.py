from flask import Blueprint, current_app, jsonify, request
from itsdangerous import BadData, SignatureExpired
from notifications_utils.url_safe_token import check_token, generate_token

from app.config import QueueNames
from app.dao.invited_user_dao import (
    get_invited_user_by_id,
    get_invited_user_by_service_and_id,
    get_invited_users_for_service,
    save_invited_user,
)
from app.dao.templates_dao import dao_get_template_by_id
from app.errors import InvalidRequest, register_errors
from app.models import BROADCAST_TYPE, EMAIL_TYPE, KEY_TYPE_NORMAL, Service
from app.notifications.process_notifications import (
    persist_notification,
    send_notification_to_queue,
)
from app.schemas import invited_user_schema

service_invite = Blueprint('service_invite', __name__)

register_errors(service_invite)


@service_invite.route('/service/<service_id>/invite', methods=['POST'])
def create_invited_user(service_id):
    request_json = request.get_json()
    invited_user, errors = invited_user_schema.load(request_json)
    save_invited_user(invited_user)

    if invited_user.service.has_permission(BROADCAST_TYPE):
        template_id = current_app.config['BROADCAST_INVITATION_EMAIL_TEMPLATE_ID']
    else:
        template_id = current_app.config['INVITATION_EMAIL_TEMPLATE_ID']

    template = dao_get_template_by_id(template_id)
    service = Service.query.get(current_app.config['NOTIFY_SERVICE_ID'])

    saved_notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=invited_user.email_address,
        service=service,
        personalisation={
            'user_name': invited_user.from_user.name,
            'service_name': invited_user.service.name,
            'url': invited_user_url(
                invited_user.id,
                request_json.get('invite_link_host'),
            ),
        },
        notification_type=EMAIL_TYPE,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        reply_to_text=invited_user.from_user.email_address
    )

    send_notification_to_queue(saved_notification, False, queue=QueueNames.NOTIFY)

    return jsonify(data=invited_user_schema.dump(invited_user).data), 201


@service_invite.route('/service/<service_id>/invite', methods=['GET'])
def get_invited_users_by_service(service_id):
    invited_users = get_invited_users_for_service(service_id)
    return jsonify(data=invited_user_schema.dump(invited_users, many=True).data), 200


@service_invite.route('/service/<service_id>/invite/<invited_user_id>', methods=['GET'])
def get_invited_user_by_service(service_id, invited_user_id):
    invited_user = get_invited_user_by_service_and_id(service_id, invited_user_id)
    return jsonify(data=invited_user_schema.dump(invited_user).data), 200


@service_invite.route('/service/<service_id>/invite/<invited_user_id>', methods=['POST'])
def update_invited_user(service_id, invited_user_id):
    fetched = get_invited_user_by_service_and_id(service_id=service_id, invited_user_id=invited_user_id)

    current_data = dict(invited_user_schema.dump(fetched).data.items())
    current_data.update(request.get_json())
    update_dict = invited_user_schema.load(current_data).data
    save_invited_user(update_dict)
    return jsonify(data=invited_user_schema.dump(fetched).data), 200


def invited_user_url(invited_user_id, invite_link_host=None):
    token = generate_token(str(invited_user_id), current_app.config['SECRET_KEY'], current_app.config['DANGEROUS_SALT'])

    if invite_link_host is None:
        invite_link_host = current_app.config['ADMIN_BASE_URL']

    return '{0}/invitation/{1}'.format(invite_link_host, token)


@service_invite.route('/invite/service/<uuid:invited_user_id>', methods=['GET'])
def get_invited_user(invited_user_id):
    invited_user = get_invited_user_by_id(invited_user_id)
    return jsonify(data=invited_user_schema.dump(invited_user).data), 200


@service_invite.route('/invite/service/<token>', methods=['GET'])
@service_invite.route('/invite/service/check/<token>', methods=['GET'])
def validate_service_invitation_token(token):

    max_age_seconds = 60 * 60 * 24 * current_app.config['INVITATION_EXPIRATION_DAYS']

    try:
        invited_user_id = check_token(token,
                                      current_app.config['SECRET_KEY'],
                                      current_app.config['DANGEROUS_SALT'],
                                      max_age_seconds)
    except SignatureExpired:
        errors = {'invitation':
                  'Your invitation to GOV.UK Notify has expired. '
                  'Please ask the person that invited you to send you another one'}
        raise InvalidRequest(errors, status_code=400)
    except BadData:
        errors = {'invitation': 'Something’s wrong with this link. Make sure you’ve copied the whole thing.'}
        raise InvalidRequest(errors, status_code=400)

    invited_user = get_invited_user_by_id(invited_user_id)
    return jsonify(data=invited_user_schema.dump(invited_user).data), 200
