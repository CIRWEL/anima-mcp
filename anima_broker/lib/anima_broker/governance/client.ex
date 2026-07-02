defmodule AnimaBroker.Governance.Client do
  @moduledoc """
  UNITARES governance check-in client — Phase 2 of the Elixir broker
  migration, SHADOW soak posture (see
  docs/plans/2026-07-01-phase2-governance-seam-addendum.md, Option A).

  Every `interval_ms` (default 180s, matching the Python bridge) it reads the
  LIVE envelope for anima/readings, maps EISV, and checks in over the fleet's
  REST tool bridge (`POST /v1/tools/call`, the pattern every BEAM client uses
  — no MCP handshake needed). The decision is written into the SHADOW
  envelope's `"governance"` slice, which nothing consumes yet: the soak is
  inert to the creature until the Python passthrough flag flips at cutover.

  Identity (operator decision, 2026-07-01): SCRATCH by default — the client
  onboards its own governance identity (`force_new`, parent chained across
  restarts via an id file, dispatch_beam pattern) and echoes the returned
  `client_session_id` on every write, which is what satisfies the strict
  gate (a transport-injected CSID does not). For the short pre-cutover
  window, set `:gov_client_session_id` (env `ANIMA_GOV_EX_CSID`) to Lumen's
  substrate CSID literal to exercise the real handshake — that mode skips
  onboard entirely.

  Failure posture (lessons imported from the fleet):
    * circuit breaker matching the Python bridge — 2 consecutive failures
      open it, backoff 15s doubling to 120s, any success resets;
    * onboard runs off the init path with its own retry backoff (5s→60s) and
      a 15s timeout — a single short timeout once left a governance feed
      dark for 9.5h (dispatch_beam lesson);
    * `AGENT_PAUSED` is classified distinctly, never swallowed as a generic
      tool error (Sentinel lesson: a paused resident stayed dark ~18h).
  """
  use GenServer
  require Logger

  alias AnimaBroker.Governance.{EisvMapper, LiveState}

  @onboard_timeout_ms 15_000
  @checkin_timeout_ms 20_000
  @onboard_retry_base_ms 5_000
  @onboard_retry_cap_ms 60_000
  @breaker_threshold 2
  @breaker_base_s 15
  @breaker_cap_s 120

  def start_link(opts),
    do: GenServer.start_link(__MODULE__, opts, name: opts[:name] || __MODULE__)

  @impl true
  def init(opts) do
    state = %{
      url: opts[:url] || Application.get_env(:anima_broker, :governance_tools_url),
      interval_ms:
        opts[:interval_ms] || Application.get_env(:anima_broker, :governance_interval_ms, 180_000),
      http_post: opts[:http_post] || (&httpc_post/4),
      id_file: opts[:id_file] || Application.get_env(:anima_broker, :gov_identity_file),
      fixed_csid: opts[:fixed_csid] || Application.get_env(:anima_broker, :gov_client_session_id),
      live_state_opts: opts[:live_state_opts] || [],
      identity: nil,
      prev_anima: nil,
      prev_readings: nil,
      failures: 0,
      breaker_backoff_s: @breaker_base_s,
      # nil = breaker closed. NEVER initialize to 0: BEAM monotonic time has an
      # arbitrary (usually negative) epoch, so `now < 0` would be true at boot
      # and silently skip every check-in.
      blocked_until_ms: nil,
      onboard_retry_ms: @onboard_retry_base_ms
    }

    cond do
      state.url == nil ->
        :ignore

      state.fixed_csid ->
        # Pre-cutover window: real substrate identity, no onboard.
        schedule_checkin(state.interval_ms)
        {:ok, %{state | identity: %{csid: state.fixed_csid, agent_uuid: nil, mode: :substrate}}}

      true ->
        send(self(), :onboard)
        {:ok, state}
    end
  end

  @impl true
  def handle_info(:onboard, state) do
    parent = load_prior_uuid(state.id_file)

    args =
      %{
        "force_new" => true,
        "spawn_reason" => "elixir_broker_shadow_soak",
        "name" => "lumen-broker-ex-shadow",
        "response_mode" => "minimal"
      }
      |> maybe_put("parent_agent_id", parent)

    case call_tool(state, "onboard", args, @onboard_timeout_ms) do
      {:ok, result} ->
        identity = %{
          csid: result["client_session_id"],
          agent_uuid: result["uuid"],
          mode: :scratch
        }

        persist_identity(state.id_file, identity)
        Logger.info("[Governance.Client] onboarded scratch identity #{identity.agent_uuid}")
        schedule_checkin(5_000)
        {:noreply, %{state | identity: identity, onboard_retry_ms: @onboard_retry_base_ms}}

      {:error, reason} ->
        Logger.warning(
          "[Governance.Client] onboard failed (#{inspect(reason)}); " <>
            "retrying in #{state.onboard_retry_ms}ms"
        )

        Process.send_after(self(), :onboard, state.onboard_retry_ms)
        next = min(state.onboard_retry_ms * 2, @onboard_retry_cap_ms)
        {:noreply, %{state | onboard_retry_ms: next}}
    end
  end

  def handle_info(:checkin, state) do
    schedule_checkin(state.interval_ms)
    {:noreply, do_checkin(state)}
  end

  defp do_checkin(%{identity: nil} = state), do: state

  defp do_checkin(state) do
    now_ms = System.monotonic_time(:millisecond)

    cond do
      is_integer(state.blocked_until_ms) and now_ms < state.blocked_until_ms ->
        state

      true ->
        case LiveState.read(state.live_state_opts) do
          {:ok, %{"anima" => anima, "readings" => readings}} ->
            attempt_checkin(state, anima, readings)

          {:error, reason} ->
            Logger.warning("[Governance.Client] live envelope unavailable (#{reason}); skipping")
            state
        end
    end
  end

  defp attempt_checkin(state, anima, readings) do
    eisv = EisvMapper.anima_to_eisv(anima, readings)

    args =
      %{
        "client_session_id" => state.identity.csid,
        "agent_name" => agent_name(state.identity),
        "complexity" => EisvMapper.estimate_complexity(anima, readings),
        "confidence" => EisvMapper.compute_confidence(anima, state.prev_anima),
        "ethical_drift" =>
          EisvMapper.compute_ethical_drift(anima, state.prev_anima, readings, state.prev_readings),
        "response_text" => EisvMapper.status_text(anima, eisv),
        "sensor_data" => %{
          "eisv" => eisv,
          "anima" => anima,
          "environment" =>
            Map.take(readings, ["ambient_temp_c", "humidity_pct", "light_lux", "pressure_hpa"])
        },
        "response_mode" => "minimal"
      }
      |> maybe_put("agent_id", state.identity.agent_uuid)

    case call_tool(state, "process_agent_update", args, @checkin_timeout_ms) do
      {:ok, result} ->
        write_governance(result, eisv, state.identity)

        %{
          state
          | prev_anima: anima,
            prev_readings: readings,
            failures: 0,
            breaker_backoff_s: @breaker_base_s
        }

      {:error, {:agent_paused, detail}} ->
        # A pause is a governance verdict, not a transport failure: record it
        # in the shadow slice and do NOT open the breaker (Sentinel lesson —
        # swallowing pause as tool_error left a resident dark for hours).
        Logger.warning("[Governance.Client] agent paused: #{inspect(detail)}")
        write_governance(%{"action" => "pause", "reason" => "agent_paused"}, eisv, state.identity)
        %{state | prev_anima: anima, prev_readings: readings}

      {:error, reason} ->
        trip_breaker(state, reason)
    end
  end

  defp trip_breaker(state, reason) do
    failures = state.failures + 1

    if failures >= @breaker_threshold do
      backoff_s = state.breaker_backoff_s

      Logger.warning(
        "[Governance.Client] check-in failed (#{inspect(reason)}); " <>
          "breaker open #{backoff_s}s after #{failures} consecutive failures"
      )

      %{
        state
        | failures: failures,
          blocked_until_ms: System.monotonic_time(:millisecond) + backoff_s * 1_000,
          breaker_backoff_s: min(backoff_s * 2, @breaker_cap_s)
      }
    else
      Logger.warning(
        "[Governance.Client] check-in failed (#{inspect(reason)}); #{failures}/#{@breaker_threshold}"
      )

      %{state | failures: failures}
    end
  end

  defp write_governance(result, eisv, identity) do
    AnimaBroker.State.Store.merge(%{
      "governance" => %{
        "action" => Map.get(result, "action", "proceed"),
        "margin" => Map.get(result, "margin", "comfortable"),
        "reason" => Map.get(result, "reason"),
        "eisv" => eisv,
        "source" => "unitares_ex",
        "identity_mode" => to_string(identity.mode),
        "unitares_agent_id" => identity.agent_uuid,
        "governance_at" => NaiveDateTime.local_now() |> NaiveDateTime.to_iso8601()
      }
    })
  end

  # -- REST tool bridge ------------------------------------------------------

  defp call_tool(state, tool, args, timeout_ms) do
    body = %{"name" => tool, "arguments" => args}

    case state.http_post.(state.url, body, headers(), timeout_ms) do
      {:ok, 200, raw} -> decode_envelope(raw)
      {:ok, status, raw} -> {:error, {:http_status, status, String.slice(raw || "", 0, 200)}}
      {:error, reason} -> {:error, {:transport, reason}}
    end
  end

  defp decode_envelope(raw) do
    case Jason.decode(raw) do
      {:ok, %{"success" => true, "result" => result}} ->
        {:ok, normalize_result(result)}

      {:ok, %{"success" => false, "error_code" => "AGENT_PAUSED"} = err} ->
        {:error, {:agent_paused, err["error"] || err["detail"]}}

      {:ok, %{"success" => false} = err} ->
        {:error, {:tool_error, err["error_code"] || err["error"]}}

      {:ok, other} ->
        {:error, {:unexpected_envelope, other}}

      {:error, _} ->
        {:error, :bad_json}
    end
  end

  # The bridge sometimes returns the tool result as a JSON string rather than
  # an object (dispatch_beam handles the same).
  defp normalize_result(result) when is_map(result), do: result

  defp normalize_result(result) when is_binary(result) do
    case Jason.decode(result) do
      {:ok, %{} = m} -> m
      _ -> %{"raw" => result}
    end
  end

  defp normalize_result(other), do: %{"raw" => other}

  defp headers do
    base = [{~c"content-type", ~c"application/json"}]

    case System.get_env("UNITARES_HTTP_API_TOKEN") do
      nil -> base
      "" -> base
      token -> [{~c"authorization", String.to_charlist("Bearer " <> token)} | base]
    end
  end

  defp httpc_post(url, body_map, headers, timeout_ms) do
    request = {String.to_charlist(url), headers, ~c"application/json", Jason.encode!(body_map)}

    case :httpc.request(:post, request, [timeout: timeout_ms], body_format: :binary) do
      {:ok, {{_, status, _}, _resp_headers, body}} -> {:ok, status, body}
      {:error, reason} -> {:error, reason}
    end
  end

  # -- identity persistence (parent chaining across restarts) ----------------

  defp load_prior_uuid(nil), do: nil

  defp load_prior_uuid(path) do
    with {:ok, raw} <- File.read(Path.expand(path)),
         {:ok, %{"agent_uuid" => uuid}} when is_binary(uuid) <- Jason.decode(raw) do
      uuid
    else
      _ -> nil
    end
  end

  defp persist_identity(nil, _identity), do: :ok

  defp persist_identity(path, identity) do
    path = Path.expand(path)
    File.mkdir_p!(Path.dirname(path))

    File.write!(
      path,
      Jason.encode!(%{"agent_uuid" => identity.agent_uuid, "client_session_id" => identity.csid})
    )
  rescue
    e -> Logger.warning("[Governance.Client] could not persist identity: #{inspect(e)}")
  end

  defp agent_name(%{mode: :substrate}), do: "Lumen"
  defp agent_name(_), do: "lumen-broker-ex"

  defp maybe_put(map, _key, nil), do: map
  defp maybe_put(map, key, value), do: Map.put(map, key, value)

  defp schedule_checkin(ms), do: Process.send_after(self(), :checkin, ms)
end
