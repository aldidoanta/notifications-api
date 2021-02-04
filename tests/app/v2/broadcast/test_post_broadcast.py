from flask import json
from freezegun import freeze_time
from tests import create_authorization_header
from unittest.mock import ANY
from . import sample_cap_xml_documents


def test_broadcast_for_service_without_permission_returns_400(
    client,
    sample_service,
):
    auth_header = create_authorization_header(service_id=sample_service.id)
    response = client.post(
        path='/v2/broadcast',
        data='',
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 400
    assert response.get_json()['errors'][0]['message'] == (
        'Service is not allowed to send broadcast messages'
    )


def test_valid_post_broadcast_returns_201(
    client,
    sample_broadcast_service,
):
    auth_header = create_authorization_header(service_id=sample_broadcast_service.id)

    response = client.post(
        path='/v2/broadcast',
        data=json.dumps({
            'content': 'This is a test',
            'reference': 'abc123',
            'category': 'Other',
            'areas': [
                {
                    'name': 'Hackney Marshes',
                    'polygons': [[
                        [-0.038280487060546875, 51.55738264619775],
                        [-0.03184318542480469, 51.553913882566754],
                        [-0.023174285888671875, 51.55812972989382],
                        [-0.023174285888671999, 51.55812972989999],
                        [-0.029869079589843747, 51.56165153059717],
                        [-0.038280487060546875, 51.55738264619775],
                    ]],
                },
            ],
        }),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 415
    assert json.loads(response.get_data(as_text=True)) == {
        'errors': [{
            'error': 'BadRequestError',
            'message': 'Content type application/json not supported'
        }],
        'status_code': 415,
    }


def test_valid_post_cap_xml_broadcast_returns_201(
    client,
    sample_broadcast_service,
):
    auth_header = create_authorization_header(service_id=sample_broadcast_service.id)

    response = client.post(
        path='/v2/broadcast',
        data=sample_cap_xml_documents.WAINFLEET,
        headers=[('Content-Type', 'application/cap+xml'), auth_header],
    )

    assert response.status_code == 201

    response_json = json.loads(response.get_data(as_text=True))

    assert response_json['approved_at'] is None
    assert response_json['approved_by_id'] == None
    assert response_json['areas'] == [
        'River Steeping in Wainfleet All Saints'
    ]
    assert response_json['cancelled_at'] == None
    assert response_json['cancelled_by_id'] == None
    assert response_json['content'].startswith(
        'A severe flood warning has been issued. Storm Dennis'
    )
    assert response_json['content'].endswith(
        'closely monitoring the situation throughout the night. '
    )
    assert response_json['reference'] == '50385fcb0ab7aa447bbd46d848ce8466E'
    assert response_json['created_at']  # datetime generated by the DB so can’t freeze it
    assert response_json['created_by_id'] == None
    assert response_json['finishes_at'] is None
    assert response_json['id'] == ANY
    assert response_json['personalisation'] is None
    assert response_json['service_id'] == str(sample_broadcast_service.id)
    assert len(response_json['simple_polygons']) == 1
    assert len(response_json['simple_polygons'][0]) == 23
    assert response_json['simple_polygons'][0][0] == [53.10561946699971, 0.2441253049430708]
    assert response_json['simple_polygons'][0][-1] == [53.10561946699971, 0.2441253049430708]
    assert response_json['starts_at'] is None
    assert response_json['status'] == 'pending-approval'
    assert response_json['template_id'] is None
    assert response_json['template_name'] is None
    assert response_json['template_version'] is None
    assert response_json['updated_at'] is None


def test_invalid_post_cap_xml_broadcast_returns_400(
    client,
    sample_broadcast_service,
):
    auth_header = create_authorization_header(service_id=sample_broadcast_service.id)

    response = client.post(
        path='/v2/broadcast',
        data="<alert>Oh no</alert>",
        headers=[('Content-Type', 'application/cap+xml'), auth_header],
    )

    assert response.status_code == 400
    assert json.loads(response.get_data(as_text=True)) == {
        'errors': [{
            'error': 'BadRequestError',
            'message': 'Request data is not valid CAP XML'
        }],
        'status_code': 400,
    }