"""Vercel Python 函数：/api/send

接收插件 POST 来的：发件邮箱(smtp_user)、邮箱授权码(smtp_password)、
亚马逊 Kindle 邮箱(kindle_email)、标题(title)、EPUB 的 base64(epub_base64)。
在本函数内用 smtplib 把 EPUB 作为附件发给亚马逊，不存储任何密码。

部署：在含本文件的目录运行 `vercel`（或 Vercel 网页导入仓库）。
依赖见同目录 requirements.txt（fastapi + mangum）。
"""
import base64
import smtplib
import ssl

from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 允许跨域：方便插件（扩展上下文）和本地调试直接调用；也兼容浏览器 fetch。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 常见邮箱服务商的 SMTP 预设；用户不手动填服务器时按发件域名自动推断。
SMTP_PRESETS = {
    "qq.com":      ("smtp.qq.com", 465, "ssl"),
    "foxmail.com": ("smtp.qq.com", 465, "ssl"),
    "163.com":     ("smtp.163.com", 465, "ssl"),
    "126.com":     ("smtp.126.com", 465, "ssl"),
    "yeah.net":    ("smtp.yeah.net", 465, "ssl"),
    "gmail.com":   ("smtp.gmail.com", 587, "tls"),
    "outlook.com": ("smtp.office365.com", 587, "tls"),
    "hotmail.com": ("smtp.office365.com", 587, "tls"),
}


def _infer_smtp(user):
    domain = user.split("@")[-1].lower()
    return SMTP_PRESETS.get(domain)


@app.post("/")
@app.post("/api/send")
async def send(req: Request):
    body = await req.json()
    user = (body.get("smtp_user") or "").strip()
    pwd = body.get("smtp_password") or ""
    kindle = (body.get("kindle_email") or "").strip()
    title = (body.get("title") or "网页转Kindle").strip() or "网页转Kindle"
    epub_b64 = body.get("epub_base64") or ""

    if not user or not pwd or not kindle:
        raise HTTPException(400, "缺少发件邮箱 / 授权码 / Kindle 邮箱")
    if not epub_b64:
        raise HTTPException(400, "缺少 EPUB 数据")

    # SMTP 服务器：优先用请求体显式指定的，否则按发件域名自动推断
    host = (body.get("smtp_host") or "").strip()
    port = int(body.get("smtp_port") or 0)
    mode = (body.get("smtp_mode") or "").lower()
    if not host:
        preset = _infer_smtp(user)
        if preset:
            host, port, mode = preset
    if not host:
        raise HTTPException(400, "无法识别邮箱服务商，请在高级选项手动填写 SMTP 服务器")
    if mode not in ("ssl", "tls"):
        mode = "ssl"

    try:
        data = base64.b64decode(epub_b64)
    except Exception:
        raise HTTPException(400, "EPUB 数据解码失败")

    if len(data) > 18 * 1024 * 1024:
        raise HTTPException(413, "EPUB 过大（>18MB），请少抓图或改用纯文字模式")

    # 构造邮件
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = kindle
    msg["Subject"] = title
    msg.attach(MIMEText("由「网页转Kindle」插件发送。", "plain", "utf-8"))

    part = MIMEBase("application", "epub+zip")
    part.set_payload(data)
    encoders.encode_base64(part)
    safe = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "note"
    part.add_header("Content-Disposition", "attachment", filename=safe + ".epub")
    msg.attach(part)

    try:
        if mode == "tls":
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, pwd)
                s.send_message(msg)
        else:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, pwd)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(
            401,
            "邮箱登录失败：请使用邮箱『授权码』而不是登录密码，并确认已开启 SMTP 服务"
            "（QQ/163 等在邮箱设置里获取授权码）。",
        )
    except smtplib.SMTPRecipientsRefused:
        raise HTTPException(400, "亚马逊拒绝该收件地址，请检查 Kindle 邮箱是否正确（应为 @kindle.com / @kindle.cn）")
    except Exception as e:
        raise HTTPException(502, f"发送失败：{e}")

    return {"ok": True, "message": f"已发送至 {kindle}"}
