import os
import random
import base64
import json
import asyncio
import re
import string
import requests
import yt_dlp
import glob
import time
import tempfile
from typing import Union
from pathlib import Path
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from pyrogram.types import Message
from pyrogram.enums import MessageEntityType
from concurrent.futures import ThreadPoolExecutor
from youtubesearchpython.__future__ import VideosSearch, CustomSearch

from TEAMZYRO.logging import LOGGER
from config import BASE_API_URL, BASE_API_KEY, time_to_seconds


DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

COOKIE_NAME = None

logger = LOGGER(__name__)

def cookie_txt_file():
    """Get random cookie file or create from server"""
    try:
        folder_path = f"{os.getcwd()}/cookies"
        filename = f"{os.getcwd()}/cookies/logs.csv"
        
        if os.path.exists(folder_path):
            txt_files = glob.glob(os.path.join(folder_path, '*.txt'))
            if txt_files:
                cookie_txt_file = random.choice(txt_files)
                with open(filename, 'a') as file:
                    file.write(f'Chosen File : {cookie_txt_file}\n')
                return f"""cookies/{str(cookie_txt_file).split("/")[-1]}"""
        
        return get_cookies_from_server()
    except Exception as e:
        logger.error(f"Error getting cookie file: {e}")
        return None

def get_cookies_from_server():
    """Get cookies from the server API"""
    global COOKIE_NAME 
    try:
        if not BASE_API_KEY or not BASE_API_URL:
            return None
            
        headers = {
            "x-api-key": BASE_API_KEY,
            "User-Agent": "Mozilla/5.0"
        }
        
        response = requests.get(f"{BASE_API_URL}/cookies", headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "success":
                COOKIE_NAME = data.get("cookie_name")
                cookie_content = base64.b64decode(data["cookies"]).decode()
                
                temp_cookie_file = os.path.join(DOWNLOAD_DIR, "temp_cookies.txt")
                with open(temp_cookie_file, "w", encoding="utf-8") as f:
                    f.write(cookie_content)
                
                return temp_cookie_file
    except Exception as e:
        logger.error(f"Error getting cookies from server: {e}")
    
    return None


def report_dead_cookie_to_server(cookie_file):
    """Tell server that a cookie is dead"""
    try:        
        cookie_name = COOKIE_NAME
        headers = {
            "x-api-key": BASE_API_KEY,
            "User-Agent": "Mozilla/5.0"
        }
        url = f"{BASE_API_URL}/mark-dead-cookie"
        data = {"cookie_name": cookie_name}
        resp = requests.post(url, json=data, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            logger.info(f"✅ Reported dead cookie to server: {cookie_name}")
        else:
            logger.warning(f"⚠️ Failed to report dead cookie: {resp.text}")
    except Exception as e:
        logger.error(f"Error reporting dead cookie: {e}")


def save_cookies_from_response(cookies_b64):
    """Save cookies from API response"""
    try:
        cookie_content = base64.b64decode(cookies_b64).decode()
        temp_cookie_file = os.path.join(DOWNLOAD_DIR, f"cookies_{int(time.time())}.txt")
        with open(temp_cookie_file, "w", encoding="utf-8") as f:
            f.write(cookie_content)
        return temp_cookie_file
    except Exception as e:
        logger.error(f"Error saving cookies: {e}")
        return None


def delete_after_use(cookie_file):
    """Remove cookie after successful use."""
    if os.path.exists(cookie_file):
        os.remove(cookie_file)

async def check_file_size(link):
    async def get_format_info(link):
        cookie_file = cookie_txt_file()
        cmd = ["yt-dlp", "-J", link]
        if cookie_file:
            cmd.extend(["--cookies", cookie_file])
            
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f'Error:\n{stderr.decode()}')
            return None
        return json.loads(stdout.decode())

    def parse_size(formats):
        total_size = 0
        for format in formats:
            if 'filesize' in format:
                total_size += format['filesize']
        return total_size

    info = await get_format_info(link)
    if info is None:
        return None
    
    formats = info.get('formats', [])
    if not formats:
        print("No formats found.")
        return None
    
    total_size = parse_size(formats)
    return total_size

async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, errorz = await proc.communicate()
    if errorz:
        if "unavailable videos are hidden" in (errorz.decode("utf-8")).lower():
            return out.decode("utf-8")
        else:
            return errorz.decode("utf-8")
    return out.decode("utf-8")


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        self.dl_stats = {
            "total_requests": 0,
            "okflix_downloads": 0,
            "cookie_downloads": 0,
            "existing_files": 0
        }

    async def _get_video_details(self, link: str, limit: int = 20) -> Union[dict, None]:
        try:
            results = VideosSearch(link, limit=limit)
            search_results = (await results.next()).get("result", [])
            
            if search_results:
                return search_results[0]
            
            search = CustomSearch(query=link, searchPreferences="EgIYAw==", limit=1)
            for res in (await search.next()).get("result", []):
                return res

            return None

        except Exception as e:
            LOGGER(__name__).error(f"Error in _get_video_details: {str(e)}")
            return None

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if re.search(self.regex, link):
            return True
        else:
            return False

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        return text[offset : offset + length]

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        result = await self._get_video_details(link)
        if not result:
            raise ValueError("Video unavailable")

        title = result["title"]
        duration_min = result.get("duration", "0:00")
        thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        vidid = result["id"]

        if str(duration_min) == "None":
            duration_sec = 0
        else:
            duration_sec = int(time_to_seconds(duration_min))

        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
            
        result = await self._get_video_details(link)
        if not result:
            raise ValueError("Video unavailable")
        return result["title"]

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        result = await self._get_video_details(link)
        if not result:
            raise ValueError("Video unavailable")
        return result.get("duration", "0:00")

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        result = await self._get_video_details(link)
        if not result:
            raise ValueError("Video unavailable")
        return result["thumbnails"][0]["url"].split("?")[0]

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        cookie_file = cookie_txt_file()
        cmd = ["yt-dlp", "-g", "-f", "best[height<=?720][width<=?1280]", link]
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
        else:
            return 0, stderr.decode()

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
            
        cookie_file = cookie_txt_file()
        cmd = f"yt-dlp -i --get-id --flat-playlist --playlist-end {limit} --skip-download {link}"
        if cookie_file:
            cmd += f" --cookies {cookie_file}"
            
        playlist = await shell_cmd(cmd)
        try:
            result = playlist.split("\n")
            for key in result:
                if key == "":
                    result.remove(key)
        except:
            result = []
        return result

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        result = await self._get_video_details(link)
        if not result:
            raise ValueError("Video unavailable")

        track_details = {
            "title": result["title"],
            "link": result["link"],
            "vidid": result["id"],
            "duration_min": result.get("duration", "0:00"),
            "thumb": result["thumbnails"][0]["url"].split("?")[0],
        }
        return track_details, result["id"]

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]
            
        cookie_file = cookie_txt_file()
        ytdl_opts = {"quiet": True}
        if cookie_file:
            ytdl_opts["cookiefile"] = cookie_file
            
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r["formats"]:
                try:
                    str(format["format"])
                except:
                    continue
                if not "dash" in str(format["format"]).lower():
                    try:
                        format["format"]
                        format["filesize"]
                        format["format_id"]
                        format["ext"]
                        format["format_note"]
                    except:
                        continue
                    formats_available.append(
                        {
                            "format": format["format"],
                            "filesize": format["filesize"],
                            "format_id": format["format_id"],
                            "ext": format["ext"],
                            "format_note": format["format_note"],
                            "yturl": link,
                        }
                    )
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        try:
            results = []
            search = VideosSearch(link, limit=10)
            search_results = (await search.next()).get("result", [])

            for result in search_results:
                results.append(result)

            if not results or query_type >= len(results):
                raise ValueError("No videos found")

            selected = results[query_type]
            return (
                selected["title"],
                selected.get("duration", "0:00"),
                selected["thumbnails"][0]["url"].split("?")[0],
                selected["id"]
            )

        except Exception as e:
            LOGGER(__name__).error(f"Error in slider: {str(e)}")
            raise ValueError("Failed to fetch video details")

    def independent_download_with_cookies(self, video_id, cookies_b64, is_video=False):
        """Download independently using provided cookies"""
        cookie_file = None
        try:
            cookie_file = get_cookies_from_server()
            if not cookie_file:
                return None
            
            ext = ".mp4" if is_video else ".mp3"
            output_file = os.path.join(DOWNLOAD_DIR, f"{video_id}{ext}")
            
            if os.path.exists(output_file):
                return output_file
            
            link = f"https://www.youtube.com/watch?v={video_id}"
            
            if is_video:
                ydl_opts = {
                    "format": "best[ext=mp4][height<=480]/best[ext=mp4]",
                    "outtmpl": os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s"),
                    "cookiefile": cookie_file,
                    "quiet": True,
                    "no_warnings": True,
                }
            else:
                ydl_opts = {
                    "format": "bestaudio/best",
                    "outtmpl": os.path.join(DOWNLOAD_DIR, f"{video_id}.%(ext)s"),
                    "cookiefile": cookie_file,
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                    "quiet": True,
                    "no_warnings": True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([link])
            
            return output_file if os.path.exists(output_file) else None
            
        except Exception as e:
            if cookie_file:
                report_dead_cookie_to_server(cookie_file)
            logger.error(f"Independent download error: {e}")
            return None
        finally:
            if cookie_file and os.path.exists(cookie_file):
                print("cookie deleting")
                os.remove(cookie_file)

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> str:
        if videoid:
            vid_id = link
            link = self.base + link
        
        if video or songvideo:
            ext = ".mp4"
        else:
            ext = ".mp3"
            
        file_path = DOWNLOAD_DIR / f"{vid_id if videoid else title}{ext}"
        
        if file_path.exists():
            return str(file_path), True
            
        loop = asyncio.get_running_loop()

        def get_ydl_opts(output_path):
            cookie_file = cookie_txt_file()
            opts = {
                "outtmpl": output_path,
                "quiet": True,
                "xff": "IN",
                "nocheckcertificate": True,
                "compat-options": "allow-unsafe-ext",
                "concurrent-fragments": 99,
                "retries": 3,
            }
            if cookie_file:
                opts["cookiefile"] = cookie_file
            return opts

        def audio_dl(vid_id):
            try:
                if not BASE_API_KEY or not BASE_API_URL:
                    print("⚙️ API KEY or URL not set in config")
                    return None
                    
                headers = {
                    "x-api-key": f"{BASE_API_KEY}",
                    "User-Agent": "Mozilla/5"
                }
                xyz = os.path.join("downloads", f"{vid_id}.mp3")
                if os.path.exists(xyz):
                    return xyz
                    
                getAudio = requests.get(f"{BASE_API_URL}/audio/{vid_id}", headers=headers, timeout=120)
                try:
                    songData = getAudio.json()
                except Exception as e:
                    print(f"Invalid response from API: {str(e)}")
                    return None
                    
                status = songData.get('status')
                if status == 'success':
                    songlink = songData['audio_url']
                    audio_url = base64.b64decode(songlink).decode()
                    ydl_opts = get_ydl_opts(xyz)
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        future = executor.submit(lambda: yt_dlp.YoutubeDL(ydl_opts).download(audio_url))
                        future.result()
                    return xyz
                elif status == 'downloading':
                    cookies_b64 = songData.get('cookies')
                    if cookies_b64:
                        print(f"🔄 Server downloading {vid_id}, starting independent download with cookies...")
                        result = self.independent_download_with_cookies(vid_id, cookies_b64, is_video=False)
                        if result:
                            return result
                    
                    print(f"⏳ Waiting for server download of {vid_id}...")
                    time.sleep(5)
                    
                    status_response = requests.get(f"{BASE_API_URL}/status/{vid_id}", headers=headers, timeout=30)
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        if status_data.get('status') == 'completed':
                            final_response = requests.get(f"{BASE_API_URL}/audio/{vid_id}", headers=headers, timeout=120)
                            if final_response.status_code == 200:
                                final_data = final_response.json()
                                if final_data.get('status') == 'success':
                                    songlink = final_data['audio_url']
                                    audio_url = base64.b64decode(songlink).decode()
                                    ydl_opts = get_ydl_opts(xyz)
                                    with ThreadPoolExecutor(max_workers=4) as executor:
                                        future = executor.submit(lambda: yt_dlp.YoutubeDL(ydl_opts).download(audio_url))
                                        future.result()
                                    return xyz
                    return None
                elif status == 'error':
                    print(f"Error: {songData.get('message', 'Unknown error from API.')}")
                    return None
                else:
                    print("Could not fetch Backend")
                    return None
            except requests.exceptions.RequestException as e:
                print(f"Network error while downloading: {str(e)}")
            except json.JSONDecodeError as e:
                print(f"Invalid response from proxy: {str(e)}")
            except Exception as e:
                print(f"Error in downloading song: {str(e)}")
            return None
        
        def video_dl(vid_id):
            try:
                if not BASE_API_KEY or not BASE_API_URL:
                    print("⚙️ API KEY or URL not set in config")
                    return None
                    
                headers = {
                    "x-api-key": f"{BASE_API_KEY}",
                    "User-Agent": "Mozilla/5"
                }
                xyz = os.path.join("downloads", f"{vid_id}.mp4")
                if os.path.exists(xyz):
                    return xyz
                    
                getVideo = requests.get(f"{BASE_API_URL}/beta/{vid_id}", headers=headers, timeout=240)
                try:
                    videoData = getVideo.json()
                except Exception as e:
                    print(f"Invalid response from API: {str(e)}")
                    return None
                    
                status = videoData.get('status')
                if status == 'success':
                    videolink = videoData['video_sd']
                    video_url = base64.b64decode(videolink).decode()
                    logger.debug(f"Got video url {video_url}")
                    ydl_opts = get_ydl_opts(f"downloads/{vid_id}.mp4")
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        future = executor.submit(lambda: yt_dlp.YoutubeDL(ydl_opts).download(video_url))
                        future.result()  
                    return xyz
                elif status == 'downloading':
                    cookies_b64 = videoData.get('cookies')
                    if cookies_b64:
                        print(f"🔄 Server downloading {vid_id}, starting independent download with cookies...")
                        result = self.independent_download_with_cookies(vid_id, cookies_b64, is_video=True)
                        if result:
                            return result
                    
                    print(f"⏳ Waiting for server download of {vid_id}...")
                    time.sleep(5)
                    
                    status_response = requests.get(f"{BASE_API_URL}/status/{vid_id}", headers=headers, timeout=30)
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        if status_data.get('status') == 'completed':
                            final_response = requests.get(f"{BASE_API_URL}/beta/{vid_id}", headers=headers, timeout=240)
                            if final_response.status_code == 200:
                                final_data = final_response.json()
                                if final_data.get('status') == 'success':
                                    videolink = final_data['video_sd']
                                    video_url = base64.b64decode(videolink).decode()
                                    ydl_opts = get_ydl_opts(f"downloads/{vid_id}.mp4")
                                    with ThreadPoolExecutor(max_workers=4) as executor:
                                        future = executor.submit(lambda: yt_dlp.YoutubeDL(ydl_opts).download(video_url))
                                        future.result()
                                    return xyz
                    return None
                elif status == 'error':
                    print(f"Error: {videoData.get('message', 'Unknown error from API.')}")
                    return None
                else:
                    print("⚙️ Could not fetch Backend")
                    return None
            except requests.exceptions.RequestException as e:
                print(f"Network error while downloading: {str(e)}")
            except json.JSONDecodeError as e:
                print(f"Invalid response from proxy: {str(e)}")
            except Exception as e:
                print(f"Error in downloading song: {str(e)}")
            return None
        
        def song_video_dl():
            formats = f"{format_id}+140"
            fpath = f"downloads/{title}"
            cookie_file = cookie_txt_file()
            ydl_optssx = {
                "format": formats,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "merge_output_format": "mp4",
            }
            if cookie_file:
                ydl_optssx["cookiefile"] = cookie_file
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])

        def song_audio_dl():
            fpath = f"downloads/{title}.%(ext)s"
            cookie_file = cookie_txt_file()
            ydl_optssx = {
                "format": format_id,
                "outtmpl": fpath,
                "geo_bypass": True,
                "nocheckcertificate": True,
                "quiet": True,
                "no_warnings": True,
                "prefer_ffmpeg": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
            if cookie_file:
                ydl_optssx["cookiefile"] = cookie_file
            x = yt_dlp.YoutubeDL(ydl_optssx)
            x.download([link])

        if songvideo:
            await loop.run_in_executor(None, song_video_dl)
            fpath = str(DOWNLOAD_DIR / f"{title}.mp4")
            return fpath
        elif songaudio:
            await loop.run_in_executor(None, song_audio_dl)
            fpath = str(DOWNLOAD_DIR / f"{title}.mp3")
            return fpath
        elif video:
            direct = True
            downloaded_file = await loop.run_in_executor(None, lambda: video_dl(vid_id))
        else:
            direct = True
            downloaded_file = await loop.run_in_executor(None, lambda: audio_dl(vid_id))
        
        return downloaded_file, direct
