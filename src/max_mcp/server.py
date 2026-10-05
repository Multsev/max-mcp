from mcp.server.fastmcp import FastMCP

from .client import lifespan
from .tools import attachments, channels, chats, messages, send

INSTRUCTIONS = (
    "Инструменты пользовательской сессии MAX. Сначала находите чат через "
    "list_chats/get_chat. Историю читайте через read_messages или "
    "list_channel_posts. search_messages выполняет локальный проход и может "
    "работать медленно. dump_channel выгружает канал частями до 1000 публикаций. "
    "Перед send_message/send_file обязательно проверьте chat_id и содержимое."
)

mcp = FastMCP("max-mcp", instructions=INSTRUCTIONS, lifespan=lifespan)
chats.register(mcp)
messages.register(mcp)
channels.register(mcp)
send.register(mcp)
attachments.register(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
