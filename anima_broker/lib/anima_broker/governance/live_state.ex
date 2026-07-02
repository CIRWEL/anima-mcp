defmodule AnimaBroker.Governance.LiveState do
  @moduledoc """
  Read-only view of the LIVE SHM envelope (the Python broker's output).

  Phase-2 seam note: anima state and most readings are still computed by the
  Python broker; the Elixir governance client reads them from the live file to
  build its check-in payload. Read-only — the single-writer-per-file rule
  holds (Python → live, Elixir → shadow).

  Returns `{:ok, %{"anima" => ..., "readings" => ...}}` only when the envelope
  is fresh (same staleness contract as the Python side's env-sensor consumer,
  default 30s); otherwise `{:error, :stale | :missing | :invalid}`.
  """

  @default_path "/dev/shm/anima_state.json"
  @default_stale_s 30

  def read(opts \\ []) do
    path = opts[:path] || Application.get_env(:anima_broker, :live_shm_path, @default_path)
    stale_s = opts[:stale_seconds] || @default_stale_s
    now = opts[:now] || NaiveDateTime.local_now()

    with {:ok, raw} <- safe_read(path),
         {:ok, envelope} <- safe_decode(raw),
         {:ok, updated_at} <- parse_updated_at(envelope),
         :fresh <- freshness(updated_at, now, stale_s),
         %{} = data <- envelope["data"] || :invalid do
      {:ok,
       %{
         "anima" => Map.get(data, "anima") || %{},
         "readings" => Map.get(data, "readings") || %{}
       }}
    else
      {:error, reason} -> {:error, reason}
      :stale -> {:error, :stale}
      :invalid -> {:error, :invalid}
    end
  end

  defp safe_read(path) do
    case File.read(path) do
      {:ok, raw} -> {:ok, raw}
      {:error, _} -> {:error, :missing}
    end
  end

  defp safe_decode(raw) do
    case Jason.decode(raw) do
      {:ok, %{} = envelope} -> {:ok, envelope}
      _ -> {:error, :invalid}
    end
  end

  defp parse_updated_at(%{"updated_at" => ts}) when is_binary(ts) do
    case NaiveDateTime.from_iso8601(ts) do
      {:ok, dt} -> {:ok, dt}
      _ -> {:error, :invalid}
    end
  end

  defp parse_updated_at(_), do: {:error, :invalid}

  defp freshness(updated_at, now, stale_s) do
    if abs(NaiveDateTime.diff(now, updated_at, :second)) <= stale_s, do: :fresh, else: :stale
  end
end
