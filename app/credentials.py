from __future__ import annotations
import sys
import keyring

SERVICE='HomeworkReminder.SMTP'

class CredentialError(Exception): pass

class WindowsVault:
    def backend(self):
        if sys.platform!='win32': raise CredentialError('本版本需要 Windows 系统凭据库；不会回退到明文存储')
        try:
            from keyring.backends.Windows import WinVaultKeyring
            backend=WinVaultKeyring()
            if backend.priority<=0: raise RuntimeError()
            return backend
        except Exception: raise CredentialError('Windows 凭据库不可用，请确认以当前 Windows 用户运行') from None

    def set(self,ref,password):
        try: self.backend().set_password(SERVICE,ref,password)
        except CredentialError: raise
        except Exception: raise CredentialError('授权码未能保存到 Windows 凭据库，配置未保存') from None

    def get(self,ref):
        try: value=self.backend().get_password(SERVICE,ref)
        except CredentialError: raise
        except Exception: raise CredentialError('无法读取 Windows 凭据库，请重新保存授权码') from None
        if not value: raise CredentialError('此邮箱尚未保存授权码，请在邮箱设置中补充')
        return value

    def delete(self,ref):
        try:
            backend=self.backend()
            if backend.get_password(SERVICE,ref): backend.delete_password(SERVICE,ref)
        except Exception: raise CredentialError('删除系统凭据失败，配置已保留，请重试') from None
