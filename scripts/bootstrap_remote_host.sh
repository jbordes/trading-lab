#!/bin/sh
# Shared POSIX bootstrap. Product setup lives in Python, not shell.
set -eu
apply=false
config=
data_dir=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --apply) apply=true; shift ;;
        --config|--data-dir)
            [ "$#" -ge 2 ] || { echo "Falta valor para $1" >&2; exit 2; }
            case "$1" in --config) config=$2 ;; --data-dir) data_dir=$2 ;; esac
            shift 2 ;;
        *) echo "Use --config archivo.json --data-dir /ruta/nueva [--apply]" >&2; exit 2 ;;
    esac
done
[ -n "$config" ] && [ -n "$data_dir" ] || { echo "Faltan --config/--data-dir" >&2; exit 2; }
[ -f "$config" ] || { echo "No existe el JSON de configuración" >&2; exit 2; }
case "$config" in /*) ;; *) echo "--config debe ser absoluto" >&2; exit 2 ;; esac
case "$data_dir" in /*) ;; *) echo "--data-dir debe ser absoluto" >&2; exit 2 ;; esac
[ ! -e "$data_dir" ] && [ ! -L "$data_dir" ] || { echo "El destino ya existe; no se toca" >&2; exit 2; }
repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$apply" = false ]; then
    echo "Vista previa de bootstrap: instalar uv si falta, Python 3.14 y dependencias locked."
    echo "Después validar JSON y crear bases/credenciales en: $data_dir"
    echo "No se modificó nada. Repetir con --apply. Tailscale se configura según el manual."
    exit 0
fi
cd "$repo"
if command -v uv >/dev/null 2>&1; then
    uv_bin=$(command -v uv)
elif [ -x "$HOME/.local/bin/uv" ]; then
    uv_bin="$HOME/.local/bin/uv"
else
    command -v curl >/dev/null 2>&1 || { echo "Instale curl y vuelva a intentar" >&2; exit 1; }
    installer=$(mktemp)
    trap 'rm -f -- "$installer"' EXIT HUP INT TERM
    curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
        https://astral.sh/uv/install.sh --output "$installer"
    UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$installer"
    uv_bin="$HOME/.local/bin/uv"
fi
"$uv_bin" sync --locked --no-dev --python 3.14
"$uv_bin" run --locked --no-sync python scripts/prepare_remote_host.py \
    --config "$config" --data-dir "$data_dir" --apply
