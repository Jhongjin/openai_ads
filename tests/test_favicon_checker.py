from __future__ import annotations

import io
import unittest

import httpx
from PIL import Image

from favicon_checker import check_favicon_url


def png_bytes(size: tuple[int, int], mode: str = "RGB", fill=(255, 255, 255)) -> bytes:
    image = Image.new(mode, size, fill)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FaviconCheckerTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_opaque_256_png_passes(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=png_bytes((256, 256)),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await check_favicon_url("https://example.com/favicon.png", client)

        self.assertEqual(result.verdict, "pass")
        self.assertEqual(result.size, "256x256")
        self.assertEqual(result.background, "불투명")

    async def test_small_png_fails(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=png_bytes((32, 32)),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await check_favicon_url("https://example.com/favicon-32x32.png", client)

        self.assertEqual(result.verdict, "fail")
        self.assertIn("이미지가 너무 작음", result.reason)

    async def test_transparent_png_warns(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=png_bytes((256, 256), mode="RGBA", fill=(255, 255, 255, 0)),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await check_favicon_url("https://example.com/favicon.png", client)

        self.assertEqual(result.verdict, "warn")
        self.assertEqual(result.background, "투명")

    async def test_tbd_waits_without_fetch(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("TBD should not fetch")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await check_favicon_url("TBD", client)

        self.assertEqual(result.verdict, "wait")


if __name__ == "__main__":
    unittest.main()
