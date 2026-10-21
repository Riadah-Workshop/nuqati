"""Meta WhatsApp webhook. No credentials or message contents are logged."""
import hashlib
import hmac
import os
import secrets
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix='/api/v1/whatsapp', tags=['WhatsApp'])

@router.get('/webhook', response_class=PlainTextResponse)
def verify_webhook(request: Request):
    q = request.query_params
    expected = os.getenv('NUQATI_WHATSAPP_VERIFY_TOKEN', '')
    supplied = q.get('hub.verify_token', '')
    challenge = q.get('hub.challenge', '')
    if (q.get('hub.mode') != 'subscribe' or not expected or
        not secrets.compare_digest(supplied, expected) or not challenge):
        raise HTTPException(status_code=403, detail='Webhook verification failed')
    return PlainTextResponse(challenge)

@router.post('/webhook')
async def receive_webhook(request: Request):
    app_secret = os.getenv('NUQATI_WHATSAPP_APP_SECRET', '')
    if not app_secret:
        raise HTTPException(status_code=503, detail='Webhook is not configured')
    raw = await request.body()
    if len(raw) > 1024 * 1024:
        raise HTTPException(status_code=413, detail='Payload too large')
    signature = request.headers.get('x-hub-signature-256', '')
    expected = 'sha256=' + hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not secrets.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail='Invalid webhook signature')
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail='Invalid JSON')
    if data.get('object') != 'whatsapp_business_account':
        raise HTTPException(status_code=400, detail='Unexpected webhook object')
    # This initial integration acknowledges authenticated test events only.
    # Do not treat incoming messages as login proof or create driver sessions here.
    return {'status': 'received'}
