import random
import json
import os
from datetime import date
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image

@register("astrbot_plugin_marry_only", "你的名字", "从群成员中随机匹配今日伴侣，每日更新，输出昵称和头像", "1.0.0")
class MarryOnlyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 数据存储路径：data/plugins/astrbot_plugin_marry_only/
        plugin_dir = os.path.dirname(__file__)
        self.data_dir = os.path.join(plugin_dir, '../../data/astrbot_plugin_marry_only')
        os.makedirs(self.data_dir, exist_ok=True)
        self.marry_file = os.path.join(self.data_dir, 'marry_data.json')

    def _read_json(self, file_path: str) -> dict:
        """读取 JSON 文件，如果不存在则返回空字典"""
        if not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_json(self, file_path: str, data: dict) -> None:
        """将数据写入 JSON 文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _build_avatar_url(self, user_id: str) -> str:
        """根据 QQ 号构造头像 URL（腾讯官方路径）"""
        return f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"

    async def _get_group_member_info(self, bot, group_id: str, user_id: str) -> dict:
        """获取单个群成员信息，返回包含昵称的字典"""
        try:
            info = await bot.call_action(
                action="get_group_member_info",
                group_id=group_id,
                user_id=user_id
            )
            return info
        except Exception:
            return None

    async def _get_all_members(self, bot, group_id: str):
        """获取群所有成员列表，返回列表，每个元素包含 user_id 和 nickname（优先群名片）"""
        try:
            member_list = await bot.call_action(
                action="get_group_member_list",
                group_id=group_id
            )
            if not member_list:
                return []
            # 提取需要的信息
            members = []
            for m in member_list:
                # 昵称优先取群名片 card，否则取昵称 nickname
                nickname = m.get('card') or m.get('nickname') or str(m['user_id'])
                members.append({
                    'user_id': str(m['user_id']),
                    'nickname': nickname
                })
            return members
        except Exception as e:
            raise e

    @filter.command("marry")
    async def marry(self, event: AstrMessageEvent):
        """今日随机匹配一名群友作为老婆，输出昵称和头像"""
        # 仅限群聊
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用。")
            return

        user_id = event.get_sender_id()
        today_str = str(date.today())
        group_key = f"{group_id}_{today_str}"

        # 读取存储的匹配数据
        marry_data = self._read_json(self.marry_file)
        if group_key not in marry_data:
            marry_data[group_key] = {}  # 格式: {用户ID: 对方ID}

        # 获取机器人自身ID（如果无法获取则设为None）
        try:
            self_id = str(event.bot.self_id)
        except:
            self_id = None

        bot = event.bot
        if not bot:
            yield event.plain_result("错误：无法获取机器人实例")
            return

        # 获取当前群成员列表（最新）
        try:
            members = await self._get_all_members(bot, group_id)
        except Exception as e:
            yield event.plain_result(f"获取群成员失败：{str(e)}")
            return

        if len(members) < 2:
            yield event.plain_result("群成员不足两人，无法匹配。")
            return

        # 构建成员ID到信息的映射
        member_dict = {m['user_id']: m for m in members}

        # 检查自己是否在成员中
        if user_id not in member_dict:
            yield event.plain_result("你不在群成员列表中，无法匹配。")
            return

        # --- 情况1：今天已经匹配过 ---
        if user_id in marry_data[group_key]:
            mate_id = marry_data[group_key][user_id]
            # 检查对方是否还在群内
            if mate_id not in member_dict:
                # 对方已离开，清空本次匹配并提示重新匹配
                del marry_data[group_key][user_id]
                self._write_json(self.marry_file, marry_data)
                yield event.plain_result("你之前的匹配对象已离开群聊，请重新发送 marry 进行匹配。")
                return
            # 获取对方信息
            mate_info = member_dict[mate_id]
            mate_nickname = mate_info['nickname']
            avatar_url = self._build_avatar_url(mate_id)
            # 发送图文消息
            yield event.chain_result([
                Plain(f"你今天的老婆是：{mate_nickname}"),
                Image.fromURL(avatar_url)
            ])
            return

        # --- 情况2：今天未匹配，进行随机匹配 ---
        # 排除自己
        candidate_ids = [m['user_id'] for m in members if m['user_id'] != user_id]
        # 排除机器人自身（如果已知且存在）
        if self_id and self_id in candidate_ids:
            candidate_ids.remove(self_id)

        if not candidate_ids:
            yield event.plain_result("排除自身后没有可匹配的群成员。")
            return

        # 随机选择一个
        mate_id = random.choice(candidate_ids)
        mate_info = member_dict[mate_id]
        mate_nickname = mate_info['nickname']
        avatar_url = self._build_avatar_url(mate_id)

        # 保存匹配结果
        marry_data[group_key][user_id] = mate_id
        self._write_json(self.marry_file, marry_data)

        # 获取发送者昵称
        sender_info = member_dict.get(user_id, {})
        sender_nickname = sender_info.get('nickname', user_id)

        # 发送图文消息
        yield event.chain_result([
            Plain(f"🎉 恭喜 {sender_nickname}，今日你的老婆是：{mate_nickname}"),
            Image.fromURL(avatar_url)
        ])
