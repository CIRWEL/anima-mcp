defmodule AnimaBroker.Governance.LiveStateTest do
  use ExUnit.Case, async: true

  alias AnimaBroker.Governance.LiveState

  @anima %{
    "warmth" => 0.4,
    "clarity" => 0.8,
    "stability" => 0.7,
    "presence" => 0.6
  }
  @readings %{"ambient_temp_c" => 24.5}

  # Same defect class as #167: these tests wrote fixed names ("anima_state.json",
  # "bad_envelope.json") straight into the shared `System.tmp_dir!()` and never
  # cleaned up. This file is `async: true`, so its own two envelope tests raced
  # each other for one path — the fresh-vs-stale distinction they assert is
  # exactly what the loser would read wrong — and the files also survived to be
  # read by later runs. Per-test directory, removed afterwards.
  setup do
    dir =
      Path.join(
        System.tmp_dir!(),
        "anima_live_state_test_#{System.pid()}_#{System.unique_integer([:positive])}"
      )

    File.rm_rf!(dir)
    File.mkdir_p!(dir)
    on_exit(fn -> File.rm_rf(dir) end)
    {:ok, dir: dir}
  end

  defp write_envelope(dir, updated_at, data \\ nil) do
    path = Path.join(dir, "anima_state.json")

    data =
      data ||
        %{
          "body_anima" => @anima,
          "anima" => %{@anima | "warmth" => 0.1},
          "readings" => @readings
        }

    File.write!(
      path,
      Jason.encode!(%{
        "updated_at" => NaiveDateTime.to_iso8601(updated_at),
        "pid" => 1,
        "data" => data
      })
    )

    path
  end

  test "fresh envelope prefers body_anima and normalizes the alias", %{dir: dir} do
    path = write_envelope(dir, NaiveDateTime.local_now())

    assert {:ok,
            %{
              "body_anima" => @anima,
              "anima" => @anima,
              "readings" => @readings
            }} = LiveState.read(path: path)
  end

  test "legacy anima remains a compatibility fallback", %{dir: dir} do
    path =
      write_envelope(
        dir,
        NaiveDateTime.local_now(),
        %{"anima" => @anima, "readings" => @readings}
      )

    assert {:ok, %{"body_anima" => @anima, "anima" => @anima}} =
             LiveState.read(path: path)
  end

  test "stale envelope is rejected", %{dir: dir} do
    path = write_envelope(dir, NaiveDateTime.add(NaiveDateTime.local_now(), -120, :second))

    assert {:error, :stale} = LiveState.read(path: path)
  end

  test "missing and invalid files degrade cleanly", %{dir: dir} do
    assert {:error, :missing} = LiveState.read(path: "/nonexistent/nope.json")

    bad = Path.join(dir, "bad_envelope.json")
    File.write!(bad, "{not json")
    assert {:error, :invalid} = LiveState.read(path: bad)

    missing_body =
      write_envelope(
        dir,
        NaiveDateTime.local_now(),
        %{"readings" => @readings}
      )

    assert {:error, :invalid} = LiveState.read(path: missing_body)
  end
end
