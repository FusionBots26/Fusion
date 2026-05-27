import os
import random
import base64
import json
import asyncio
import re
import glob
import time
import requests
import yt_dlp

from pathlib import Path
from typing import Union
from concurrent.futures import ThreadPoolExecutor

from pyrogram.types import Message
from pyrogram.enums import MessageEntityType

from youtubesearchpython.__future__ import VideosSearch

from TEAMZYRO.logging import LOGGER
from config import BASE_API_URL, BASE_API_KEY, time_to_seconds


DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

COOKIE_NAME = None
logger = LOGGER(__name__)


def safe_filename(name: str):
    if not name:
        name = f"file_{int(time.time())}"

    return re.sub(r'[\\/*?:"<>|]', "_", str(name))


def safe_thumbnail(result):
    try:
        thumbs = result.get("thumbnails") or []

        if not thumbs:
            return None

        thumb = thumbs[0]

        if not isinstance(thumb, dict):
            return None

        url = thumb.get("url")

        if not url:
            return None

        return url.split("?")[0]

    except Exception:
        return None


def cookie_txt_file():
    try:
        folder_path = f"{os.getcwd()}/cookies"
        filename = f"{os.getcwd()}/cookies/logs.csv"

        if os.path.exists(folder_path):
            txt_files = glob.glob(os.path.join(folder_path, '*.txt'))

            if txt_files:
                selected = random.choice(txt_files)

                with open(filename, 'a') as file:
                    file.write(f'Chosen File : {selected}\n')

                return selected

        return get_cookies_from_server()

    except Exception as e:
        logger.error(f"Cookie error: {e}")
        return None


def get_cookies_from_server():
    global COOKIE_NAME

    try:
        if not BASE_API_KEY or not BASE_API_URL:
            return None

        headers = {
            "x-api-key": BASE_API_KEY,
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(
            f"{BASE_API_URL}/cookies",
            headers=headers,
            timeout=30,
        )

        if response.status_code != 200:
            return None

        try:
            data = response.json()
        except Exception:
            logger.error(f"Invalid cookie API response: {response.text}")
            return None

        if data.get("status") != "success":
            return None

        COOKIE_NAME = data.get("cookie_name")

        cookie_content = base64.b64decode(
            data["cookies"]
        ).decode()

        temp_cookie_file = os.path.join(
            DOWNLOAD_DIR,
            "temp_cookies.txt",
        )

        with open(temp_cookie_file, "w", encoding="utf-8") as f:
            f.write(cookie_content)

        return temp_cookie_file

    except Exception as e:
        logger.error(f"Cookie server error: {e}")
        return None


def report_dead_cookie_to_server(cookie_file):
    try:
        if not COOKIE_NAME:
            return

        headers = {
            "x-api-key": BASE_API_KEY,
            "User-Agent": "Mozilla/5.0",
        }

        data = {
            "cookie_name": COOKIE_NAME,
        }

        requests.post(
            f"{BASE_API_URL}/mark-dead-cookie",
            json=data,
            headers=headers,
            timeout=10,
        )

    except Exception as e:
        logger.error(f"Dead cookie report error: {e}")


async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    out, err = await proc.communicate()

    stderr = err.decode("utf-8", errors="ignore")
    stdout = out.decode("utf-8", errors="ignore")

    if stderr:
        if "unavailable videos are hidden" in stderr.lower():
            return stdout

        return stderr

    return stdout


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.listbase = "https://youtube.com/playlist?list="

    async def _get_video_details(
        self,
        link: str,
        limit: int = 5,
    ):

        try:

            link = str(link).strip()

            if "youtube.com" in link or "youtu.be" in link:

                video_id = None

                if "v=" in link:
                    video_id = (
                        link.split("v=")[-1]
                        .split("&")[0]
                        .strip()
                    )

                elif "youtu.be/" in link:
                    video_id = (
                        link.split("youtu.be/")[-1]
                        .split("?")[0]
                        .strip()
                    )

                return {
                    "title": "YouTube Video",
                    "duration": "0:00",
                    "id": video_id,
                    "link": link,
                    "thumbnails": [],
                }

            search = VideosSearch(
                link,
                limit=limit,
            )

            data = await search.next()

            results = data.get("result", [])

            if not results:
                return None

            return results[0]

        except Exception as e:
            logger.error(f"_get_video_details fatal: {e}")
            return None

    async def exists(self, link: str, videoid=False):
        if videoid:
            link = self.base + link

        return bool(re.search(self.regex, link))

    async def url(self, message_1: Message):
        messages = [message_1]

        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)

        for message in messages:
            entities = (
                message.entities
                or message.caption_entities
                or []
            )

            for entity in entities:
                if entity.type == MessageEntityType.URL:
                    text = message.text or message.caption or ""

                    return text[
                        entity.offset:
                        entity.offset + entity.length
                    ]

                elif entity.type == MessageEntityType.TEXT_LINK:
                    return entity.url

        return None

    async def details(self, link: str, videoid=False):
        if videoid:
            link = self.base + link

        link = link.split("&")[0]
        link = link.split("?si=")[0]

        result = await self._get_video_details(link)

        if not result:
            raise ValueError("Video unavailable")

        title = result.get("title") or "Unknown"

        duration_min = result.get("duration") or "0:00"

        vidid = result.get("id")

        if not vidid:
            raise ValueError("Missing video ID")

        thumbnail = safe_thumbnail(result)

        try:
            duration_sec = int(time_to_seconds(duration_min))
        except Exception:
            duration_sec = 0

        return (
            title,
            duration_min,
            duration_sec,
            thumbnail,
            vidid,
        )

    async def title(self, link: str, videoid=False):
        data = await self.details(link, videoid)
        return data[0]

    async def duration(self, link: str, videoid=False):
        data = await self.details(link, videoid)
        return data[1]

    async def thumbnail(self, link: str, videoid=False):
        data = await self.details(link, videoid)
        return data[3]

    async def track(self, link: str, videoid=False):
        if videoid:
            link = self.base + link

        result = await self._get_video_details(link)

        if not result:
            raise ValueError("Video unavailable")

        track_details = {
            "title": result.get("title") or "Unknown",
            "link": result.get("link") or link,
            "vidid": result.get("id"),
            "duration_min": result.get("duration") or "0:00",
            "thumb": safe_thumbnail(result),
        }

        return track_details, result.get("id")

    async def video(self, link: str, videoid=False):
        if videoid:
            link = self.base + link

        cookie_file = cookie_txt_file()

        cmd = [
            "yt-dlp",
            "-g",
            "-f",
            "best[height<=?720][width<=?1280]",
            link,
        ]

        if cookie_file:
            cmd.extend(["--cookies", cookie_file])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        if stdout:
            return 1, stdout.decode().split("\n")[0]

        return 0, stderr.decode()

    async def playlist(self, link, limit, user_id, videoid=False):
        if videoid:
            link = self.listbase + link

        cookie_file = cookie_txt_file()

        cmd = (
            f"yt-dlp -i --get-id "
            f"--flat-playlist "
            f"--playlist-end {limit} "
            f"--skip-download {link}"
        )

        if cookie_file:
            cmd += f" --cookies {cookie_file}"

        playlist = await shell_cmd(cmd)

        result = [
            x.strip()
            for x in playlist.split("\n")
            if x.strip()
        ]

        return result

    async def slider(
        self,
        link: str,
        query_type: int,
        videoid=False,
    ):
        try:
            if videoid:
                link = self.base + link

            search = VideosSearch(link, limit=10)

            data = await search.next()

            results = data.get("result", [])

            if not results:
                raise ValueError("No videos found")

            if query_type >= len(results):
                raise ValueError("Invalid query index")

            selected = results[query_type]

            return (
                selected.get("title") or "Unknown",
                selected.get("duration") or "0:00",
                safe_thumbnail(selected),
                selected.get("id"),
            )

        except Exception as e:
            logger.error(f"slider error: {e}")
            raise ValueError("Failed to fetch video details")

    async def formats(self, link, videoid=False):
        if videoid:
            link = self.base + link

        cookie_file = cookie_txt_file()

        ydl_opts = {
            "quiet": True,
        }

        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file

        formats_available = []

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                link,
                download=False,
            )

            for fmt in info.get("formats", []):

                if "dash" in str(
                    fmt.get("format", "")
                ).lower():
                    continue

                if not fmt.get("format_id"):
                    continue

                formats_available.append(
                    {
                        "format": fmt.get("format"),
                        "filesize": fmt.get("filesize"),
                        "format_id": fmt.get("format_id"),
                        "ext": fmt.get("ext"),
                        "format_note": fmt.get("format_note"),
                        "yturl": link,
                    }
                )

        return formats_available, link

    async def download(
        self,
        link: str,
        mystic,
        video=False,
        videoid=False,
        songaudio=False,
        songvideo=False,
        format_id=None,
        title=None,
    ):

        if videoid:
            vid_id = link
            link = self.base + link
        else:
            vid_id = None

        ext = ".mp4" if (video or songvideo) else ".mp3"

        safe_name = (
            vid_id
            if vid_id
            else safe_filename(title)
        )

        file_path = DOWNLOAD_DIR / f"{safe_name}{ext}"

        if file_path.exists():
            return str(file_path), True

        loop = asyncio.get_running_loop()

        def get_ydl_opts(output_path):
            cookie_file = cookie_txt_file()

            opts = {
                "outtmpl": output_path,
                "quiet": True,
                "nocheckcertificate": True,
                "geo_bypass": True,
                "retries": 3,
            }

            if cookie_file:
                opts["cookiefile"] = cookie_file

            return opts

        def direct_download(url, output_path):
            try:
                ydl_opts = get_ydl_opts(output_path)

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                return output_path

            except Exception as e:
                logger.error(f"Download error: {e}")
                return None

        if songvideo:
            output = f"downloads/{safe_name}.mp4"

            ydl_opts = {
                "format": f"{format_id}+140",
                "outtmpl": output,
                "merge_output_format": "mp4",
                "quiet": True,
            }

            await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(
                    ydl_opts
                ).download([link]),
            )

            return output

        if songaudio:
            output = f"downloads/{safe_name}.%(ext)s"

            ydl_opts = {
                "format": format_id,
                "outtmpl": output,
                "quiet": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }

            await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(
                    ydl_opts
                ).download([link]),
            )

            return f"downloads/{safe_name}.mp3"

        if not BASE_API_KEY or not BASE_API_URL:
            raise ValueError("API config missing")

        headers = {
            "x-api-key": BASE_API_KEY,
            "User-Agent": "Mozilla/5.0",
        }

        try:
            endpoint = (
                f"{BASE_API_URL}/beta/{vid_id}"
                if video
                else f"{BASE_API_URL}/audio/{vid_id}"
            )

            response = requests.get(
                endpoint,
                headers=headers,
                timeout=240,
            )

            try:
                data = response.json()
            except Exception:
                logger.error(
                    f"Invalid API response: {response.text}"
                )
                return None

            status = data.get("status")

            if status != "success":
                raise ValueError(
                    data.get("message", "API failed")
                )

            encoded_url = (
                data.get("video_sd")
                if video
                else data.get("audio_url")
            )

            if not encoded_url:
                raise ValueError("Missing media URL")

            media_url = base64.b64decode(
                encoded_url
            ).decode()

            downloaded = await loop.run_in_executor(
                None,
                lambda: direct_download(
                    media_url,
                    str(file_path),
                ),
            )

            if not downloaded:
                raise ValueError("Download failed")

            return downloaded, True

        except Exception as e:
            logger.error(f"download() error: {e}")
            return None
