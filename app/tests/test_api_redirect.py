from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

app = FastAPI()

@app.get('/api', include_in_schema=False)
async def _redirect_root() -> RedirectResponse:
    return RedirectResponse('/api/v1', status_code=308)

@app.get('/api/{path:path}', include_in_schema=False)
async def _catch_all(path: str) -> RedirectResponse:
    raise HTTPException(status_code=404)

client = TestClient(app)

def test_api_redirect_root():
    resp = client.get('/api', follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers['location'] == '/api/v1'

def test_api_no_redirect_other():
    resp = client.get('/api/foo', follow_redirects=False)
    assert resp.status_code == 404
