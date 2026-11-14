"""Executable security unit checks that do not need a running PostgreSQL service."""
import asyncio
import os
from unittest.mock import patch

from fastapi import HTTPException
from app.auth import allow, hash_password
from app.auth_limits import verify_or_dummy
from app.teltonika_receiver import receive, crc16_ibm, parse_avl, remote_is_allowed


def test_password_verification_known_unknown():
    good=hash_password('hello-world-password')
    assert verify_or_dummy('hello-world-password',good)
    assert not verify_or_dummy('wrong-password',good)
    assert not verify_or_dummy('hello-world-password',None)


def test_role_guard_blocks_driver():
    driver=type('U',(),{'role':'driver'})()
    try:
        allow(driver,'company_admin','fleet_manager')
        assert False,'driver should not be allowed'
    except HTTPException as exc:
        assert exc.status_code==403


def test_tracker_allowlist():
    with patch.dict(os.environ,{'TELTONIKA_ALLOWED_CIDRS':'192.0.2.0/24,10.0.0.4/32'}):
        assert remote_is_allowed(('192.0.2.22',5001))
        assert remote_is_allowed(('10.0.0.4',5027))
        assert not remote_is_allowed(('192.0.3.1',5027))
        assert not remote_is_allowed(('10.0.0.5',5027))


def test_teltonika_codec_and_async_receiver():
    # Minimal Codec 8 packet: zero records, accepted handshake, zero-record ack.
    payload=b'\x08\x00\x00'
    assert parse_avl(payload)==[]
    async def exercise():
        with patch('app.teltonika_receiver.known_device',return_value=True),patch('app.teltonika_receiver.persist',return_value=True):
            server=await asyncio.start_server(receive,'127.0.0.1',0)
            port=server.sockets[0].getsockname()[1]
            async with server:
                reader,writer=await asyncio.open_connection('127.0.0.1',port)
                imei=b'012345678901234'
                writer.write(len(imei).to_bytes(2,'big')+imei)
                await writer.drain()
                assert await asyncio.wait_for(reader.readexactly(1),2)==b'\x01'
                frame=b'\x00'*4+len(payload).to_bytes(4,'big')+payload+crc16_ibm(payload).to_bytes(4,'big')
                writer.write(frame);await writer.drain()
                assert await asyncio.wait_for(reader.readexactly(4),2)==b'\x00'*4
                writer.close();await writer.wait_closed()
    with patch.dict(os.environ,{'TELTONIKA_ALLOWED_CIDRS':'127.0.0.1/32'}):
        asyncio.run(exercise())
