"""Synthetic speaking-style variants of existing bank questions (the persona set).

Each persona asks the same eight things as the base questions, in a different voice. The wording
is invented by the developer to look like those speakers; it is NOT real user data and must not
be mixed with the frozen acceptance set. Scores are reported per persona, apart from the core set.
Expected answers are inherited from the base question, so they stay known by construction.
"""

from __future__ import annotations

BASES = ("Q02", "Q06", "Q15", "Q13", "Q44", "Q45", "Q56", "Q59")

PERSONAS: dict[str, tuple[str, ...]] = {
    "kansai": (  # Kansai dialect Japanese
        "うち、初めて京都行ったんいつやったっけ？",
        "小明と最後に会うたん、いつやった？",
        "こないだの頭痛、いつやったかな？",
        "猫の単語、最後に覚えなおしたんいつやろ？",
        "浅草寺って何回行ったことあるん？",
        "ラーメン何回食べたかなぁ、数えてくれへん？",
        "二週間前、うち何書いてたん？",
        "沖縄って行ったことあるっけ？",
    ),
    "taiwan": (  # colloquial Taiwanese Mandarin
        "我人生第一次踏進京都是幾號啊",
        "跟小明上次碰到面是哪一天齁",
        "我上次頭很痛是什麼時候啦",
        "那個猫的單字我上次背是啥時候",
        "淺草寺我到底去過幾次啊",
        "拉麵我是吃了幾碗了喔",
        "前兩週我寫了啥東西",
        "我有去過沖繩嗎啦",
    ),
    "japanese_mixed": (  # mostly Japanese, some Chinese
        "初めて京都に行ったの、いつだっけ？ 日期給我",
        "小明と最後に会った日は？",
        "最後に頭痛したのっていつ？",
        "猫の単語を最後に復習したの、何日？",
        "浅草寺に行った回数、教えて。",
        "ラーメン食べた回数は？ 全部列出來",
        "2週間前に何を書いたか教えて",
        "沖縄に行ったことある？",
    ),
    "formal": (  # formal written Chinese
        "請問本人首次造訪京都之日期為何？",
        "請問本人最後一次與小明會面之日期為何？",
        "請問本人最近一次頭痛發生於何時？",
        "請問本人最後一次複習單字「猫」之日期為何？",
        "請彙整本人前往淺草寺之次數與日期。",
        "請彙整本人食用拉麵之次數與日期。",
        "請列出本人兩週前所撰寫之紀錄。",
        "請確認本人是否曾造訪沖繩。",
    ),
    "terse": (  # minimal typing, no grammar
        "初京都 何時",
        "小明 最後 見面",
        "頭痛 上次",
        "猫 單字 上次複習",
        "淺草寺 幾次",
        "拉麵 幾次",
        "兩週前 寫啥",
        "沖繩 去過?",
    ),
    "elder": (  # an older, polite, slow speaker
        "我想問一下啊，我第一次到京都玩是哪一天呢？你幫我查查看",
        "上一次跟小明見面是什麼時候啊？我記不得了",
        "我上次頭痛是哪一天？不記得了，麻煩你找一找",
        "那個貓的日文字，我上一次複習是哪一天呢？",
        "淺草寺我去過幾次呀？麻煩你幫我算一算",
        "拉麵我吃過幾次呢？你幫我數一數好嗎",
        "兩個星期前我記了些什麼啊？",
        "我有沒有去過沖繩呢？",
    ),
}
