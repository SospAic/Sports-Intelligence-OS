#!/usr/bin/env python3
"""Minimal private-network CDP HTTP/WebSocket forwarder.

Recent Chromium builds may keep DevTools bound to loopback even when a remote
debugging address is supplied. This proxy keeps Chromium on 127.0.0.1:9223
and exposes only the Compose-internal browser:9222 endpoint to the API.
"""

from __future__ import annotations

import asyncio
import os


LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("SIO_BROWSER_CDP_PORT", "9222"))
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = int(os.environ.get("SIO_BROWSER_CHROME_CDP_PORT", "9223"))
PUBLIC_HOST = os.environ.get("SIO_BROWSER_CDP_PUBLIC_HOST", "browser")


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65_536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        # Half-close the destination so the peer can finish its close frame.
        # Closing the whole writer here can tear down a healthy CDP websocket
        # as soon as the opposite direction briefly reaches EOF.
        if not writer.is_closing():
            try:
                writer.write_eof()
                await writer.drain()
            except (AttributeError, ConnectionError, OSError):
                pass


async def _read_headers(reader: asyncio.StreamReader) -> bytes:
    return await reader.readuntil(b"\r\n\r\n")


def _is_websocket_request(headers: bytes) -> bool:
    lowered = headers.lower()
    return b"upgrade: websocket" in lowered and b"connection:" in lowered


def _rewrite_request_headers(headers: bytes) -> bytes:
    lines = headers.rstrip(b"\r\n").split(b"\r\n")
    rewritten = [
        b"Host: 127.0.0.1:" + str(UPSTREAM_PORT).encode()
        if line.lower().startswith(b"host:")
        else b"Origin: http://127.0.0.1:" + str(UPSTREAM_PORT).encode()
        if line.lower().startswith(b"origin:")
        else line
        for line in lines
    ]
    return b"\r\n".join(rewritten) + b"\r\n\r\n"


def _rewrite_websocket_urls(body: bytes) -> bytes:
    replacements = (
        (f"127.0.0.1:{UPSTREAM_PORT}".encode(), f"{PUBLIC_HOST}:{LISTEN_PORT}".encode()),
        (f"localhost:{UPSTREAM_PORT}".encode(), f"{PUBLIC_HOST}:{LISTEN_PORT}".encode()),
    )
    for source, target in replacements:
        body = body.replace(source, target)
    return body


async def _read_http_body(
    reader: asyncio.StreamReader, response_headers: bytes
) -> bytes:
    lowered = response_headers.lower()
    marker = b"content-length:"
    if marker in lowered:
        line = next(line for line in lowered.split(b"\r\n") if line.startswith(marker))
        return await reader.readexactly(int(line.split(b":", 1)[1].strip()))
    if b"transfer-encoding: chunked" in lowered:
        chunks: list[bytes] = []
        while True:
            size_line = await reader.readuntil(b"\r\n")
            size = int(size_line.strip().split(b";", 1)[0], 16)
            if size == 0:
                await reader.readexactly(2)
                break
            chunks.append(await reader.readexactly(size))
            await reader.readexactly(2)
        return b"".join(chunks)
    return await reader.read()


def _replace_content_length(headers: bytes, length: int) -> bytes:
    lines = headers.rstrip(b"\r\n").split(b"\r\n")
    rewritten = [
        b"Content-Length: " + str(length).encode()
        if line.lower().startswith(b"content-length:")
        else line
        for line in lines
    ]
    return b"\r\n".join(rewritten) + b"\r\n\r\n"


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    upstream_writer: asyncio.StreamWriter | None = None
    try:
        request_headers = await _read_headers(reader)
        upstream_reader, upstream_writer = await asyncio.open_connection(
            UPSTREAM_HOST, UPSTREAM_PORT
        )
        upstream_writer.write(_rewrite_request_headers(request_headers))
        await upstream_writer.drain()
        if _is_websocket_request(request_headers):
            response_headers = await _read_headers(upstream_reader)
            writer.write(response_headers)
            await writer.drain()
            if not response_headers.startswith(b"HTTP/1.1 101"):
                return
            await asyncio.gather(_pipe(reader, upstream_writer), _pipe(upstream_reader, writer))
            return
        response_headers = await _read_headers(upstream_reader)
        body = _rewrite_websocket_urls(
            await _read_http_body(upstream_reader, response_headers)
        )
        writer.write(_replace_content_length(response_headers, len(body)))
        writer.write(body)
        await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError, asyncio.TimeoutError, OSError, ValueError):
        pass
    finally:
        if upstream_writer is not None and not upstream_writer.is_closing():
            upstream_writer.close()
        if not writer.is_closing():
            writer.close()
        await writer.wait_closed()


async def main() -> None:
    server = await asyncio.start_server(_handle, LISTEN_HOST, LISTEN_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
