from fastapi.testclient import TestClient

from src.host.app import app


def test_health_discovered_without_db():
    with TestClient(app) as client:
        response = client.get('/api/v1/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
    routes = [r.path for r in app.routes]
    assert routes.count('/api/v1/health') == 1


def test_openapi_health_route():
    schema = app.openapi()
    assert '/api/v1/health' in schema['paths']
