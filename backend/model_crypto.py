"""
model_crypto.py — AES-256 加解密工具

用于保护 ONNX 模型文件:
  - 加密: ONNX → .enc (AES-256-CBC)
  - 解密: .enc → 内存中的 bytes (不落盘)

加密格式:
  [32 bytes: HMAC-SHA256] [16 bytes: IV] [N bytes: ciphertext]
"""

import hashlib
import hmac
import os
import struct
from pathlib import Path

# ---------------------------------------------------------------------------
# 密钥 — 硬编码在代码中, PyInstaller 编译后成为字节码
# 实际密钥由 PBKDF2 派生, 不直接使用原始字符串
# ---------------------------------------------------------------------------
_RAW_KEY = "AestheticLens_2026_arch_v2_cl1p_v1tl14"
_SALT = b"\xa3\xf1\x9c\x2b\x7d\xe0\x48\x56\x82\x1a\xcf\x3d\xb7\x90\x6e\x14"


def _derive_key() -> bytes:
    """从硬编码字符串派生 32 字节 AES 密钥"""
    return hashlib.pbkdf2_hmac("sha256", _RAW_KEY.encode(), _SALT, 100_000, dklen=32)


def encrypt_file(input_path: str, output_path: str) -> None:
    """加密文件 → .enc"""
    key = _derive_key()

    with open(input_path, "rb") as f:
        plaintext = f.read()

    iv = os.urandom(16)

    # AES-256-CBC
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding

    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    # HMAC 校验
    mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()

    with open(output_path, "wb") as f:
        f.write(mac + iv + ciphertext)

    print(f"  Encrypted: {input_path} → {output_path}")


def decrypt_to_bytes(enc_path: str) -> bytes:
    """解密 .enc 文件 → bytes (纯内存, 不落盘)"""
    key = _derive_key()

    with open(enc_path, "rb") as f:
        data = f.read()

    stored_mac = data[:32]
    iv = data[32:48]
    ciphertext = data[48:]

    # 验证 HMAC
    expected_mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(stored_mac, expected_mac):
        raise ValueError(f"HMAC verification failed: {enc_path}")

    # 解密
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = sym_padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()

    return plaintext
