import Config

# Read deployment overrides from the environment at release start, matching how
# the Python services are configured. Skipped in :test (see config.exs).
if config_env() != :test do
  config :anima_broker,
    shm_path: System.get_env("ANIMA_SHM_PATH") || "/dev/shm/anima_state.shadow.json",
    tick_interval_ms: String.to_integer(System.get_env("ANIMA_TICK_MS") || "2000"),
    # I2C sensors only start when a bus is named (e.g. ANIMA_I2C_BUS=i2c-1 on the
    # Pi). Unset => no sensors (dev/CI), broker still boots and writes the
    # envelope. nil rather than "" so the supervisor's is_nil check is clean.
    i2c_bus: System.get_env("ANIMA_I2C_BUS"),
    # Phase-2 governance client (shadow soak). Only starts when a tools URL is
    # set, e.g. UNITARES_TOOLS_URL=http://<mac-tailscale-ip>:8767/v1/tools/call.
    governance_tools_url: System.get_env("UNITARES_TOOLS_URL"),
    governance_interval_ms:
      String.to_integer(System.get_env("ANIMA_GOVERNANCE_INTERVAL_SECONDS") || "180") * 1000,
    live_shm_path: System.get_env("ANIMA_LIVE_SHM_PATH") || "/dev/shm/anima_state.json",
    gov_identity_file: System.get_env("ANIMA_GOV_EX_ID_FILE") || "~/.anima/gov_ex_identity.json",
    # Pre-cutover window only: set to Lumen's substrate client_session_id
    # literal to exercise the real identity handshake (skips scratch onboard).
    gov_client_session_id: System.get_env("ANIMA_GOV_EX_CSID")
end
