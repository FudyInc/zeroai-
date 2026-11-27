#!/usr/bin/env python3
"""Crea o actualiza un usuario del login local de emergencia (users.json).

    python3 scripts/crear-usuario-local.py

Pide usuario, rol (siempre explícito) y contraseña (con getpass: la contraseña nunca va por argumento
ni queda en el historial del shell). Escribe users.json con permisos 600. Si el
usuario ya existe, le cambia la contraseña y el rol (y con eso invalida sus tokens
anteriores). Si users.json existe pero está corrupto, avisa y NO lo sobrescribe.

users.json está en .gitignore; la ruta se puede cambiar con AUTH_USERS_PATH.
No imprime nunca la contraseña ni el hash.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zero import auth   # noqa: E402
from zero._env import load_env   # noqa: E402
from zero.config import (   # noqa: E402
    LOCAL_LOGIN_MIN_PASSWORD_LEN, LOCAL_LOGIN_ROLES, LOCAL_LOGIN_SCOPED_ROLES,
)


def main() -> int:
    load_env()   # mismo .env que el servidor: así AUTH_USERS_PATH coincide
    print(f"Archivo de usuarios: {auth._users_path().resolve()}")
    if auth.users_file_broken():
        print(f"{auth._users_path()} existe pero está corrupto — arréglalo a mano; no se toca.")
        return 1
    username = input("Usuario: ").strip()
    existente = auth._read_users().get(username)
    if existente is not None and not existente.get("role"):
        print(f"{username!r} existe sin rol (hoy entraría como admin): elige uno explícito.")
    role = input(f"Rol ({'/'.join(LOCAL_LOGIN_ROLES)}): ").strip()
    if role not in LOCAL_LOGIN_ROLES:
        print(f"Rol inválido: {role!r}")
        return 1
    clients = []
    if role in LOCAL_LOGIN_SCOPED_ROLES:
        clients = [c.strip() for c in input("Clientes (ids separados por coma): ").split(",") if c.strip()]
        if not clients:
            print(f"El rol {role} necesita al menos un cliente.")
            return 1
    password = getpass.getpass("Contraseña: ")
    if len(password) < LOCAL_LOGIN_MIN_PASSWORD_LEN:
        print(f"La contraseña debe tener al menos {LOCAL_LOGIN_MIN_PASSWORD_LEN} caracteres.")
        return 1
    if getpass.getpass("Repite la contraseña: ") != password:
        print("Las contraseñas no coinciden.")
        return 1
    try:
        auth.add_user(username, password, role=role, clients=clients)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"Listo: usuario {username!r} con rol {role} guardado en {auth._users_path().resolve()} (permisos 600).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
