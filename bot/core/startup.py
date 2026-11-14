from aiofiles.os import path as aiopath, remove, makedirs
from aiofiles import open as aiopen
from aioshutil import rmtree
from asyncio import create_subprocess_exec, create_subprocess_shell, sleep
from importlib import import_module
from os import getenv

from .. import (
    aria2_options,
    qbit_options,
    nzb_options,
    drives_ids,
    drives_names,
    index_urls,
    user_data,
    excluded_extensions,
    included_extensions,
    LOGGER,
    rss_dict,
    sabnzbd_client,
    auth_chats,
    sudo_users,
)
from ..helper.ext_utils.db_handler import database
from .config_manager import Config, BinConfig
from .telegram_manager import TgClient
from .torrent_manager import TorrentManager


async def update_qb_options():
    LOGGER.info("Get qBittorrent options from server")
    if not qbit_options:
        opt = await TorrentManager.qbittorrent.app.preferences()
        qbit_options.update(opt)
        del qbit_options["listen_port"]
        for k in list(qbit_options.keys()):
            if k.startswith("rss"):
                del qbit_options[k]
        qbit_options["web_ui_password"] = "cloudsync2026"
        await TorrentManager.qbittorrent.app.set_preferences(
            {"web_ui_password": "cloudsync2026"}
        )
    else:
        await TorrentManager.qbittorrent.app.set_preferences(qbit_options)


async def update_aria2_options():
    LOGGER.info("Get aria2 options from server")
    if not aria2_options:
        op = await TorrentManager.aria2.getGlobalOption()
        aria2_options.update(op)
    else:
        await TorrentManager.aria2.changeGlobalOption(aria2_options)


async def update_nzb_options():
    LOGGER.info("Get SABnzbd options from server")
    while True:
        try:
            no = (await sabnzbd_client.get_config())["config"]["misc"]
            nzb_options.update(no)
        except:
            await sleep(0.5)
            continue
        break


async def load_settings():
    if not Config.DATABASE_URL:
        return

    for p in ["thumbnails", "tokens", "rclone"]:
        if await aiopath.exists(p):
            await rmtree(p, ignore_errors=True)

    await database.connect()
    if database.db is None:
        return

    BOT_ID = Config.BOT_TOKEN.split(":", 1)[0]

    try:
        settings = import_module("config")
        config_file = {
            key: value.strip() if isinstance(value, str) else value
            for key, value in vars(settings).items()
            if not key.startswith("__")
        }
    except ModuleNotFoundError:
        config_file = {}

    old_config = await database.db.settings.deployConfig.find_one(
        {"_id": BOT_ID}, {"_id": 0}
    )
    if old_config is None and config_file:
        await database.db.settings.deployConfig.replace_one(
            {"_id": BOT_ID}, config_file, upsert=True
        )
    elif old_config and config_file and old_config != config_file:
        LOGGER.info("Replacing existing deploy config in Database")
        await database.db.settings.deployConfig.replace_one(
            {"_id": BOT_ID}, config_file, upsert=True
        )
    else:
        config_dict = await database.db.settings.config.find_one(
            {"_id": BOT_ID}, {"_id": 0}
        )
        if config_dict:
            Config.load_dict(config_dict)

    if pf_dict := await database.db.settings.files.find_one(
        {"_id": BOT_ID}, {"_id": 0}
    ):
        for key, value in pf_dict.items():
            if value:
                file_ = key.replace("__", ".")
                async with aiopen(file_, "wb+") as f:
                    await f.write(value)

    if a2c_options := await database.db.settings.aria2c.find_one(
        {"_id": BOT_ID}, {"_id": 0}
    ):
        aria2_options.update(a2c_options)

    if qbit_opt := await database.db.settings.qbittorrent.find_one(
        {"_id": BOT_ID}, {"_id": 0}
    ):
        qbit_options.update(qbit_opt)

    if nzb_opt := await database.db.settings.nzb.find_one({"_id": BOT_ID}, {"_id": 0}):
        if await aiopath.exists("sabnzbd/SABnzbd.ini.bak"):
            await remove("sabnzbd/SABnzbd.ini.bak")
        ((key, value),) = nzb_opt.items()
        file_ = key.replace("__", ".")
        async with aiopen(f"sabnzbd/{file_}", "wb+") as f:
            await f.write(value)

    if await database.db.users.find_one():
        for p in ["thumbnails", "tokens", "rclone"]:
            if not await aiopath.exists(p):
                await makedirs(p)
        rows = database.db.users.find({})
        async for row in rows:
            uid = row["_id"]
            del row["_id"]
            thumb_path = f"thumbnails/{uid}.jpg"
            rclone_config_path = f"rclone/{uid}.conf"
            token_path = f"tokens/{uid}.pickle"
            if row.get("THUMBNAIL"):
                async with aiopen(thumb_path, "wb+") as f:
                    await f.write(row["THUMBNAIL"])
                row["THUMBNAIL"] = thumb_path
            if row.get("RCLONE_CONFIG"):
                async with aiopen(rclone_config_path, "wb+") as f:
                    await f.write(row["RCLONE_CONFIG"])
                row["RCLONE_CONFIG"] = rclone_config_path
            if row.get("TOKEN_PICKLE"):
                async with aiopen(token_path, "wb+") as f:
                    await f.write(row["TOKEN_PICKLE"])
                row["TOKEN_PICKLE"] = token_path
            user_data[uid] = row
        LOGGER.info("Users data has been imported from Database")

    if await database.db.rss[BOT_ID].find_one():
        rows = database.db.rss[BOT_ID].find({})
        async for row in rows:
            user_id = row["_id"]
            del row["_id"]
            rss_dict[user_id] = row
        LOGGER.info("Rss data has been imported from Database.")


async def save_settings():
    if database.db is None:
        return
    config_dict = Config.get_all()
    await database.db.settings.config.replace_one(
        {"_id": TgClient.ID}, config_dict, upsert=True
    )
    if await database.db.settings.aria2c.find_one({"_id": TgClient.ID}) is None:
        await database.db.settings.aria2c.update_one(
            {"_id": TgClient.ID}, {"$set": aria2_options}, upsert=True
        )
    if await database.db.settings.qbittorrent.find_one({"_id": TgClient.ID}) is None:
        await database.save_qbit_settings()
    if await database.db.settings.nzb.find_one({"_id": TgClient.ID}) is None:
        async with aiopen("sabnzbd/SABnzbd.ini", "rb+") as pf:
            nzb_conf = await pf.read()
        await database.db.settings.nzb.update_one(
            {"_id": TgClient.ID}, {"$set": {"SABnzbd__ini": nzb_conf}}, upsert=True
        )


async def update_variables():
    if (
        Config.LEECH_SPLIT_SIZE > TgClient.MAX_SPLIT_SIZE
        or Config.LEECH_SPLIT_SIZE == 2097152000
        or not Config.LEECH_SPLIT_SIZE
    ):
        Config.LEECH_SPLIT_SIZE = TgClient.MAX_SPLIT_SIZE

    Config.HYBRID_LEECH = bool(Config.HYBRID_LEECH and TgClient.IS_PREMIUM_USER)

    if Config.AUTHORIZED_CHATS:
        aid = Config.AUTHORIZED_CHATS.split()
        for id_ in aid:
            chat_id, *thread_ids = id_.split("|")
            chat_id = int(chat_id.strip())
            if thread_ids:
                thread_ids = list(map(lambda x: int(x.strip()), thread_ids))
                auth_chats[chat_id] = thread_ids
            else:
                auth_chats[chat_id] = []

    if Config.SUDO_USERS:
        aid = Config.SUDO_USERS.split()
        for id_ in aid:
            sudo_users.append(int(id_.strip()))

    if Config.EXCLUDED_EXTENSIONS:
        fx = Config.EXCLUDED_EXTENSIONS.split()
        for x in fx:
            x = x.lstrip(".")
            excluded_extensions.append(x.strip().lower())

    if Config.INCLUDED_EXTENSIONS:
        fx = Config.INCLUDED_EXTENSIONS.split()
        for x in fx:
            x = x.lstrip(".")
            included_extensions.append(x.strip().lower())

    if Config.GDRIVE_ID:
        drives_names.append("Main")
        drives_ids.append(Config.GDRIVE_ID)
        index_urls.append(Config.INDEX_URL)

    if await aiopath.exists("list_drives.txt"):
        async with aiopen("list_drives.txt", "r+") as f:
            lines = await f.readlines()
            for line in lines:
                temp = line.split()
                drives_ids.append(temp[1])
                drives_names.append(temp[0].replace("_", " "))
                if len(temp) > 2:
                    index_urls.append(temp[2])
                else:
                    index_urls.append("")


async def load_configurations():

    if not await aiopath.exists(".netrc"):
        async with aiopen(".netrc", "w"):
            pass

    await (
        await create_subprocess_shell(
            f"chmod 600 .netrc && cp .netrc /root/.netrc && chmod +x services.sh && ./services.sh {BinConfig.ARIA2_NAME} {BinConfig.QBIT_NAME} {BinConfig.SABNZBD_NAME}"
        )
    ).wait()

    web_port = getenv("PORT") or Config.BASE_URL_PORT or 80
    if Config.BASE_URL or getenv("PORT"):
        await create_subprocess_shell(
            f"gunicorn -k uvicorn.workers.UvicornWorker -w 1 web.wserver:app --bind 0.0.0.0:{web_port}"
        )

    if await aiopath.exists("cfg.zip"):
        if await aiopath.exists("/JDownloader/cfg"):
            await rmtree("/JDownloader/cfg", ignore_errors=True)
        await (
            await create_subprocess_exec(BinConfig.SEVENZ_NAME, "x", "cfg.zip", "-o/JDownloader")
        ).wait()

    if await aiopath.exists("accounts.zip"):
        if await aiopath.exists("accounts"):
            await rmtree("accounts")
        await (
            await create_subprocess_exec(
                BinConfig.SEVENZ_NAME, "x", "-o.", "-aoa", "accounts.zip", "accounts/*.json"
            )
        ).wait()
        await (await create_subprocess_exec("chmod", "-R", "777", "accounts")).wait()
        await remove("accounts.zip")

    if not await aiopath.exists("accounts"):
        Config.USE_SERVICE_ACCOUNTS = False


async def set_bot_commands():
    from pyrogram.types import BotCommand
    from ..helper.telegram_helper.bot_commands import BotCommands

    def _cmd(val):
        c = val[0] if isinstance(val, list) else val
        return c.lower()

    commands_list = [
        BotCommand(_cmd(BotCommands.LeechCommand), "Leech file/link to Telegram"),
        BotCommand(_cmd(BotCommands.QbLeechCommand), "Leech torrent using qBittorrent"),
        BotCommand(_cmd(BotCommands.MirrorCommand), "Mirror file/link to cloud"),
        BotCommand(_cmd(BotCommands.QbMirrorCommand), "Mirror torrent using qBittorrent"),
        BotCommand(_cmd(BotCommands.JdMirrorCommand), "Mirror link using JDownloader"),
        BotCommand(_cmd(BotCommands.JdLeechCommand), "Leech link using JDownloader"),
        BotCommand(_cmd(BotCommands.NzbMirrorCommand), "Mirror NZB using SABnzbd"),
        BotCommand(_cmd(BotCommands.NzbLeechCommand), "Leech NZB using SABnzbd"),
        BotCommand(_cmd(BotCommands.YtdlCommand), "Mirror yt-dlp supported link"),
        BotCommand(_cmd(BotCommands.YtdlLeechCommand), "Leech yt-dlp supported link"),
        BotCommand(_cmd(BotCommands.GallerydlCommand), "Mirror gallery-dl supported link"),
        BotCommand(_cmd(BotCommands.GallerydlLeechCommand), "Leech gallery-dl supported link"),
        BotCommand(_cmd(BotCommands.CloneCommand), "Copy file/folder to Google Drive or Rclone"),
        BotCommand(_cmd(BotCommands.ListCommand), "Search files in Google Drive"),
        BotCommand(_cmd(BotCommands.SearchCommand), "Search torrents via plugins/API"),
        BotCommand(_cmd(BotCommands.NzbSearchCommand), "Search NZB via NZBHydra"),
        BotCommand(_cmd(BotCommands.CountCommand), "Count files/folders in Google Drive"),
        BotCommand(_cmd(BotCommands.DeleteCommand), "Delete file/folder from Google Drive"),
        BotCommand(_cmd(BotCommands.SelectCommand), "Select files from torrent/NZB task"),
        BotCommand(_cmd(BotCommands.ForceStartCommand), "Force start queued task"),
        BotCommand(_cmd(BotCommands.CancelTaskCommand), "Cancel a specific task"),
        BotCommand(_cmd(BotCommands.CancelAllCommand), "Cancel all active tasks"),
        BotCommand(_cmd(BotCommands.StatusCommand), "Show active tasks status"),
        BotCommand(_cmd(BotCommands.StatsCommand), "Show bot & system resource stats"),
        BotCommand(_cmd(BotCommands.RssCommand), "Open RSS subscription menu"),
        BotCommand(_cmd(BotCommands.UserSetCommand), "Open user settings panel"),
        BotCommand(_cmd(BotCommands.BotSetCommand), "Open bot settings panel (Owner/Sudo)"),
        BotCommand(_cmd(BotCommands.UsersCommand), "View users settings (Owner/Sudo)"),
        BotCommand(_cmd(BotCommands.AuthorizeCommand), "Authorize a user or chat"),
        BotCommand(_cmd(BotCommands.UnAuthorizeCommand), "Unauthorize a user or chat"),
        BotCommand(_cmd(BotCommands.AddSudoCommand), "Promote user to sudo"),
        BotCommand(_cmd(BotCommands.RmSudoCommand), "Demote sudo user"),
        BotCommand(_cmd(BotCommands.PingCommand), "Test bot latency"),
        BotCommand(_cmd(BotCommands.RestartCommand), "Restart the bot"),
        BotCommand(_cmd(BotCommands.LogCommand), "Get bot runtime logs"),
        BotCommand(_cmd(BotCommands.HelpCommand), "Get detailed command usage guide"),
    ]
    try:
        await TgClient.bot.set_bot_commands(commands_list)
        LOGGER.info(f"Auto-registered {len(commands_list)} bot commands with Telegram!")
    except Exception as e:
        LOGGER.error(f"Failed to auto-register bot commands: {e}")
