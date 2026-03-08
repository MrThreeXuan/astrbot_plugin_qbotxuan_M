import random
import json
import os
from datetime import date
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image

@register("astrbot_plugin_marry_advanced", "你的名字", "每日随机配对群友，支持禁止组合、预设情侣", "1.0.0")
class MarryAdvancedPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        plugin_dir = os.path.dirname(__file__)
        self.data_dir = os.path.join(plugin_dir, '../../data/astrbot_plugin_marry_advanced')
        os.makedirs(self.data_dir, exist_ok=True)
        self.marry_file = os.path.join(self.data_dir, 'marry_data.json')
        self.forbid_file = os.path.join(self.data_dir, 'forbidden.json')
        self.couple_file = os.path.join(self.data_dir, 'couples.json')  # 新增预设情侣存储
        self._load_data()

    def _load_data(self):
        """加载配对数据、禁止列表和预设情侣"""
        self.marry_data = self._read_json(self.marry_file)
        self.forbidden = self._read_json(self.forbid_file)
        self.couples = self._read_json(self.couple_file)  # 格式: {group_id: [[uid1, uid2], ...]}

    def _save_marry_data(self):
        self._write_json(self.marry_file, self.marry_data)

    def _save_forbidden(self):
        self._write_json(self.forbid_file, self.forbidden)

    def _save_couples(self):
        self._write_json(self.couple_file, self.couples)

    def _read_json(self, file_path: str) -> dict:
        if not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_json(self, file_path: str, data: dict) -> None:
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _is_forbidden(self, group_id: str, uid1: str, uid2: str) -> bool:
        """检查两个用户是否被禁止配对"""
        if uid1 == uid2:
            return True
        group_forbid = self.forbidden.get(str(group_id), [])
        pair = tuple(sorted([uid1, uid2]))
        return any(tuple(sorted(p)) == pair for p in group_forbid)

    def _build_avatar_url(self, user_id: str) -> str:
        return f"https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640"

    async def _get_group_members(self, bot, group_id: str):
        """获取群成员列表，返回 [{user_id, nickname}]，排除机器人自身"""
        try:
            member_list = await bot.call_action(
                action="get_group_member_list",
                group_id=group_id
            )
            if not member_list:
                return []
            try:
                self_id = str(bot.self_id)
            except:
                self_id = None

            members = []
            for m in member_list:
                uid = str(m['user_id'])
                if self_id and uid == self_id:
                    continue
                nickname = m.get('card') or m.get('nickname') or uid
                members.append({'user_id': uid, 'nickname': nickname})
            return members
        except Exception as e:
            raise e

    async def _generate_pairs_for_group(self, group_id: str, members: list):
        """
        为给定群生成当日配对，返回 {uid: mate_uid} 映射，保证双射。
        优先分配预设情侣，剩余成员随机配对。
        """
        member_ids = [m['user_id'] for m in members]
        # 获取本群预设情侣（双方都在群内且未被禁止）
        group_couples = self.couples.get(str(group_id), [])
        valid_couples = []
        used = set()
        for a, b in group_couples:
            a, b = str(a), str(b)
            if a in member_ids and b in member_ids and not self._is_forbidden(group_id, a, b):
                valid_couples.append((a, b))
        # 分配预设情侣，避免冲突（一个人只能在一对中）
        assigned_pairs = {}
        for a, b in valid_couples:
            if a in used or b in used:
                continue
            assigned_pairs[a] = b
            assigned_pairs[b] = a
            used.add(a)
            used.add(b)
        # 剩余成员
        remaining = [uid for uid in member_ids if uid not in used]
        # 对剩余成员进行随机配对（考虑禁止列表）
        random.shuffle(remaining)
        # 尝试最多100次随机打乱，找到合法配对
        final_pairs = assigned_pairs.copy()
        for attempt in range(100):
            random.shuffle(remaining)
            valid = True
            temp_pairs = {}
            # 处理剩余成员（两两配对）
            for i in range(0, len(remaining), 2):
                if i + 1 < len(remaining):
                    a, b = remaining[i], remaining[i + 1]
                    if self._is_forbidden(group_id, a, b):
                        valid = False
                        break
                    temp_pairs[a] = b
                    temp_pairs[b] = a
                else:
                    # 奇数，最后一人单身
                    last = remaining[i]
                    temp_pairs[last] = last
            if valid:
                final_pairs.update(temp_pairs)
                break
        else:
            # 100次都失败，忽略禁止强制配对（仅用于剩余成员）
            for i in range(0, len(remaining), 2):
                if i + 1 < len(remaining):
                    a, b = remaining[i], remaining[i + 1]
                    final_pairs[a] = b
                    final_pairs[b] = a
                else:
                    last = remaining[i]
                    final_pairs[last] = last
        return final_pairs

    async def _ensure_pairs(self, bot, group_id: str, today: str):
        """确保当天配对已生成，若未生成则生成并保存"""
        key = f"{group_id}_{today}"
        if key in self.marry_data:
            return self.marry_data[key]
        members = await self._get_group_members(bot, group_id)
        if len(members) < 2:
            return None
        pairs = await self._generate_pairs_for_group(group_id, members)
        self.marry_data[key] = pairs
        self._save_marry_data()
        return pairs

    async def _get_member_nickname(self, bot, group_id: str, user_id: str) -> str:
        """获取单个群成员昵称"""
        try:
            info = await bot.call_action(
                action="get_group_member_info",
                group_id=group_id,
                user_id=user_id
            )
            return info.get('card') or info.get('nickname') or user_id
        except:
            return user_id

    # ==================== 指令部分 ====================

    @filter.command("marry")
    async def marry(self, event: AstrMessageEvent):
        """今日随机匹配一名群友作为老婆"""
        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用。")
            return

        user_id = event.get_sender_id()
        today = str(date.today())
        bot = event.bot
        if not bot:
            yield event.plain_result("错误：无法获取机器人实例")
            return

        pairs = await self._ensure_pairs(bot, group_id, today)
        if pairs is None:
            yield event.plain_result("群成员不足两人，无法配对。")
            return

        if user_id not in pairs:
            yield event.plain_result("你不在群成员列表中，无法配对。")
            return

        mate_id = pairs[user_id]
        if mate_id == user_id:
            yield event.plain_result("今日你是单身贵族，没有老婆。")
            return

        mate_nick = await self._get_member_nickname(bot, group_id, mate_id)
        avatar_url = self._build_avatar_url(mate_id)

        yield event.chain_result([
            Plain(f"你今日的群友老婆是：{mate_nick}"),
            Image.fromURL(avatar_url)
        ])

    @filter.command("request_pool")
    async def request_pool(self, event: AstrMessageEvent):
        """查看指定群的当日配对列表，用法：request_pool 群号（所有群成员可用）"""
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            yield event.plain_result("请指定群号：request_pool 群号")
            return
        target_group = parts[1]
        if not target_group.isdigit():
            yield event.plain_result("群号必须为数字")
            return

        today = str(date.today())
        key = f"{target_group}_{today}"
        bot = event.bot
        if not bot:
            yield event.plain_result("无法获取机器人实例")
            return

        try:
            members = await self._get_group_members(bot, target_group)
        except Exception as e:
            yield event.plain_result(f"获取群成员失败：{e}")
            return
        member_dict = {m['user_id']: m['nickname'] for m in members}

        if key not in self.marry_data:
            yield event.plain_result("该群今天尚未生成配对，请先有人使用 marry 指令触发生成。")
            return

        pairs = self.marry_data[key]
        lines = ["今日配对列表："]
        paired = set()
        for uid, mate in pairs.items():
            if uid in paired:
                continue
            if uid == mate:
                lines.append(f"单身：{member_dict.get(uid, uid)}")
                paired.add(uid)
            else:
                lines.append(f"{member_dict.get(uid, uid)} 的配偶是 {member_dict.get(mate, mate)}")
                paired.add(uid)
                paired.add(mate)

        result = "\n".join(lines)
        yield event.plain_result(result)

    @filter.command("forbid_couple")
    async def forbid_couple(self, event: AstrMessageEvent):
        """禁止两个QQ号配对，用法：forbid_couple QQ1 QQ2（所有群成员可用）"""
        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("请指定两个QQ号：forbid_couple QQ1 QQ2")
            return
        uid1, uid2 = parts[1], parts[2]
        if not uid1.isdigit() or not uid2.isdigit():
            yield event.plain_result("QQ号必须为数字")
            return
        if uid1 == uid2:
            yield event.plain_result("不能禁止自己与自己配对。")
            return

        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用。")
            return

        self._load_data()
        group_forbid = self.forbidden.get(str(group_id), [])
        pair = sorted([uid1, uid2])
        if pair in group_forbid:
            yield event.plain_result("该组合已在禁止列表中。")
            return

        group_forbid.append(pair)
        self.forbidden[str(group_id)] = group_forbid
        self._save_forbidden()

        # 重新生成今日配对
        today = str(date.today())
        key = f"{group_id}_{today}"
        bot = event.bot
        try:
            members = await self._get_group_members(bot, group_id)
            if len(members) >= 2:
                pairs = await self._generate_pairs_for_group(group_id, members)
                self.marry_data[key] = pairs
                self._save_marry_data()
                yield event.plain_result(f"已禁止 {uid1} 和 {uid2} 配对，今日配对已重新生成。")
            else:
                yield event.plain_result("群成员不足，无法重新生成配对。")
        except Exception as e:
            yield event.plain_result(f"重新生成配对失败：{e}")

    @filter.command("couple_set")
    async def couple_set(self, event: AstrMessageEvent):
        """设置预设情侣，用法：couple_set QQ1 QQ2（所有群成员可用）"""
        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("请指定两个QQ号：couple_set QQ1 QQ2")
            return
        uid1, uid2 = parts[1], parts[2]
        if not uid1.isdigit() or not uid2.isdigit():
            yield event.plain_result("QQ号必须为数字")
            return
        if uid1 == uid2:
            yield event.plain_result("不能将自己设为自己情侣。")
            return

        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用。")
            return

        self._load_data()
        group_couples = self.couples.get(str(group_id), [])
        pair = sorted([uid1, uid2])
        if pair in group_couples:
            yield event.plain_result("该组合已是预设情侣。")
            return

        group_couples.append(pair)
        self.couples[str(group_id)] = group_couples
        self._save_couples()

        # 重新生成今日配对以立即生效
        today = str(date.today())
        key = f"{group_id}_{today}"
        bot = event.bot
        try:
            members = await self._get_group_members(bot, group_id)
            if len(members) >= 2:
                pairs = await self._generate_pairs_for_group(group_id, members)
                self.marry_data[key] = pairs
                self._save_marry_data()
                yield event.plain_result(f"已设置 {uid1} 和 {uid2} 为预设情侣，今日配对已重新生成。")
            else:
                yield event.plain_result("群成员不足，无法重新生成配对。")
        except Exception as e:
            yield event.plain_result(f"重新生成配对失败：{e}")

    @filter.command("couple_del")
    async def couple_del(self, event: AstrMessageEvent):
        """移除预设情侣，用法：couple_del QQ1 QQ2（所有群成员可用）"""
        parts = event.message_str.strip().split()
        if len(parts) < 3:
            yield event.plain_result("请指定两个QQ号：couple_del QQ1 QQ2")
            return
        uid1, uid2 = parts[1], parts[2]
        if not uid1.isdigit() or not uid2.isdigit():
            yield event.plain_result("QQ号必须为数字")
            return

        group_id = event.get_group_id()
        if not group_id:
            yield event.plain_result("该指令只能在群聊中使用。")
            return

        self._load_data()
        group_couples = self.couples.get(str(group_id), [])
        pair = sorted([uid1, uid2])
        if pair not in group_couples:
            yield event.plain_result("该组合不在预设情侣列表中。")
            return

        group_couples.remove(pair)
        self.couples[str(group_id)] = group_couples
        self._save_couples()

        # 重新生成今日配对
        today = str(date.today())
        key = f"{group_id}_{today}"
        bot = event.bot
        try:
            members = await self._get_group_members(bot, group_id)
            if len(members) >= 2:
                pairs = await self._generate_pairs_for_group(group_id, members)
                self.marry_data[key] = pairs
                self._save_marry_data()
                yield event.plain_result(f"已移除 {uid1} 和 {uid2} 的预设情侣关系，今日配对已重新生成。")
            else:
                yield event.plain_result("群成员不足，无法重新生成配对。")
        except Exception as e:
            yield event.plain_result(f"重新生成配对失败：{e}")
