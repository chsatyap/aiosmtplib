"""
Protocol level tests.
"""
import asyncio
import socket

import pytest

from aiosmtplib import SMTPResponseException, SMTPServerDisconnected
from aiosmtplib.protocol import SMTPProtocol


pytestmark = pytest.mark.asyncio()


async def test_protocol_connect(echo_server, event_loop, hostname, port):
    connect_future = event_loop.create_connection(
        SMTPProtocol, host=hostname, port=port
    )
    transport, protocol = await asyncio.wait_for(connect_future, timeout=1.0)

    assert protocol._transport is transport
    assert not protocol._transport.is_closing()

    transport.close()


async def test_protocol_read_limit_overrun(
    event_loop, bind_address, hostname, port, monkeypatch
):
    async def client_connected(reader, writer):
        await reader.read(1000)
        long_response = (
            b"220 At vero eos et accusamus et iusto odio dignissimos ducimus qui "
            b"blanditiis praesentium voluptatum deleniti atque corruptis qui "
            b"blanditiis praesentium voluptatum\n"
        )
        writer.write(long_response)
        await writer.drain()

    server = await asyncio.start_server(
        client_connected, host=bind_address, port=port, family=socket.AF_INET
    )
    connect_future = event_loop.create_connection(
        SMTPProtocol, host=hostname, port=port
    )

    _, protocol = await asyncio.wait_for(connect_future, timeout=1.0)

    monkeypatch.setattr("aiosmtplib.protocol.MAX_LINE_LENGTH", 128)

    with pytest.raises(SMTPResponseException) as exc_info:
        await protocol.execute_command(b"TEST\n", timeout=1.0)

    assert exc_info.value.code == 500
    assert "Line too long" in exc_info.value.message

    server.close()
    await server.wait_closed()


async def test_protocol_connected_check_on_read_response(monkeypatch):
    protocol = SMTPProtocol()
    monkeypatch.setattr(protocol, "_transport", None)

    with pytest.raises(SMTPServerDisconnected):
        await protocol.read_response(timeout=1.0)


async def test_protocol_reader_connected_check_on_start_tls(client_tls_context):
    smtp_protocol = SMTPProtocol()

    with pytest.raises(SMTPServerDisconnected):
        await smtp_protocol.start_tls(client_tls_context, timeout=1.0)


async def test_protocol_writer_connected_check_on_start_tls(client_tls_context):
    smtp_protocol = SMTPProtocol()

    with pytest.raises(SMTPServerDisconnected):
        await smtp_protocol.start_tls(client_tls_context)


async def test_error_on_readline_with_partial_line(
    event_loop, bind_address, hostname, port
):
    partial_response = b"499 incomplete response\\"

    async def client_connected(reader, writer):
        writer.write(partial_response)
        writer.write_eof()
        await writer.drain()

    server = await asyncio.start_server(
        client_connected, host=bind_address, port=port, family=socket.AF_INET
    )
    connect_future = event_loop.create_connection(
        SMTPProtocol, host=hostname, port=port
    )

    _, protocol = await asyncio.wait_for(connect_future, timeout=1.0)

    with pytest.raises(SMTPServerDisconnected):
        await protocol.read_response(timeout=1.0)

    server.close()
    await server.wait_closed()
