"""Run locally with the service stopped. No command-line passwords; never touches SMTP credentials."""
import getpass
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from argon2 import PasswordHasher
from filelock import FileLock, Timeout
from sqlalchemy import delete
from app.config import Settings
from app.models import LoginSession, Setting, database

def main():
    settings=Settings.from_env()
    if not (settings.data_dir/'app.db').exists():raise SystemExit('尚无数据库，请先启动应用完成初始化。')
    lock=FileLock(str(settings.data_dir/'application.lock'))
    try:lock.acquire(timeout=0)
    except Timeout:raise SystemExit('请先停止正在运行的应用，再重置密码。') from None
    engine=None
    try:
        password=getpass.getpass('新管理员密码（至少 12 个字符）：')
        if not 12<=len(password)<=128:raise SystemExit('密码长度必须为 12–128 个字符。')
        if getpass.getpass('再次输入新密码：')!=password:raise SystemExit('两次密码不一致，未修改数据。')
        hashed=PasswordHasher().hash(password);password=None
        engine,Session=database(settings.data_dir/'app.db')
        with Session() as db:
            s=db.get(Setting,'admin_hash')
            if not s:raise SystemExit('尚未初始化，请从本机网页设置密码。')
            s.value=hashed;db.execute(delete(LoginSession));db.commit()
        print('管理员密码已重置，旧会话已退出；名单、通知和 SMTP 凭据未修改。')
    finally:
        if engine:engine.dispose()
        lock.release()
if __name__=='__main__':main()
