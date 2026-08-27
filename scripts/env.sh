#!/usr/bin/env bash

resolve_env_file() {
  local root_dir="$1"
  local env_file="$2"

  if [[ "$env_file" = /* ]]; then
    printf '%s\n' "$env_file"
  else
    printf '%s\n' "$root_dir/$env_file"
  fi
}

env_local_file() {
  local env_file="$1"
  printf '%s.local\n' "$env_file"
}

load_env_file() {
  local env_file="$1"
  [[ -f "$env_file" ]] || return 0

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"

    [[ -z "${line//[[:space:]]/}" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" == *"="* ]] || continue

    local key="${line%%=*}"
    local value="${line#*=}"

    key="${key#"${key%%[![:space:]]*}"}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"

    if [[ "$value" =~ ^\".*\"$ || "$value" =~ ^\'.*\'$ ]]; then
      value="${value:1:-1}"
    fi

    export "$key=$value"
  done < "$env_file"
}

merged_env_args() {
  local base_env_file="$1"
  local local_env_file="$2"

  printf -- '--env-file\n%s\n' "$base_env_file"
  if [[ -f "$local_env_file" ]]; then
    printf -- '--env-file\n%s\n' "$local_env_file"
  fi
}
