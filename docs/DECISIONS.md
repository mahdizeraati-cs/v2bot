# Decisions (append-only, dated, one line each)

2026-11-06: group_mode = "all" fixed for all PasarGuard servers; no selective group mode. All enabled groups are sent for every user on that server.
2026-11-06: Server registration is rejected if ping() fails (no saving with a warning).
2026-11-06: PanelType enum values = pasarguard | marzban | hiddify. Legacy server rows default to pasarguard via server_default.
2026-11-06: Panel credentials (username/password/API key) are stored in existing servers columns; type-specific extras go in servers.panel_config (JSONB). Password remains plaintext in DB (pre-existing, not changed in this task).
2026-11-06: Hiddify remote_id is a deterministic UUID5 per server+username; subscription URL built from client_proxy_path via panel_config.sub_url_template.
2026-11-06: MarzbanClient.get_users/get_resources/update_user/delete_user/revoke_sub/reset_usage are dead code (no callers) and are removed.
