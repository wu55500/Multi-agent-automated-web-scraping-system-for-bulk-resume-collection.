"""半自动填表：复用你自己已登录的浏览器，只填字段，提交永远由人点。

这里只实现用户控制的填表。平台适配及自动提交由单独的已授权集成负责。

用法：
    python3 -m dz.cli fill --job <id> --url <你手动打开的岗位页>
脚本会填完字段然后停下来，等你看一眼、自己点"发送"。
"""
from __future__ import annotations

PROFILE = {
    "name": "你的姓名",
    "phone": "1xxxxxxxxxx",
    "email": "you@example.com",
    "city": "上海",
}


def guard(allow_submit: bool = False):
    if allow_submit:
        raise NotImplementedError(
            "旧版填表适配器不提供自动提交；请使用 platform 中的授权投递工作流。"
            "")


def fill(page, profile: dict | None = None, url: str = "") -> None:
    guard(False)
    p = {**PROFILE, **(profile or {})}
    if url:
        page.goto(url)
    for sel, val in (("#name", p["name"]), ("#phone", p["phone"]), ("#email", p["email"])):
        try:
            page.fill(sel, val, timeout=3000)
        except Exception:
            continue  # 页面结构各异，填不进去就跳过，绝不猜选择器乱点
    print("字段已填。请自己核对并点『发送』；脚本不会、也不该替你点。")


def run(job_url: str, profile: dict | None = None, profile_dir: str = "") -> None:
    """需要在装了 playwright 的机器上跑；手机端只跑 offlline 流水线。"""
    from playwright.sync_api import sync_playwright

    guard(False)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=profile_dir or "./chrome-profile",
            channel="chrome", headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        fill(page, profile, job_url)
        input("按回车结束（确认你已经自己点过提交）")
        ctx.close()
