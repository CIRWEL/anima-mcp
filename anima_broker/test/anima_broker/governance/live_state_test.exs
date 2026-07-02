defmodule AnimaBroker.Governance.LiveStateTest do
  use ExUnit.Case, async: true

  alias AnimaBroker.Governance.LiveState

  @anima %{"warmth" => 0.4, "clarity" => 0.8}
  @readings %{"ambient_temp_c" => 24.5}

  defp write_envelope(dir, updated_at) do
    path = Path.join(dir, "anima_state.json")

    File.write!(
      path,
      Jason.encode!(%{
        "updated_at" => NaiveDateTime.to_iso8601(updated_at),
        "pid" => 1,
        "data" => %{"anima" => @anima, "readings" => @readings}
      })
    )

    path
  end

  test "fresh envelope yields anima and readings" do
    dir = System.tmp_dir!()
    path = write_envelope(dir, NaiveDateTime.local_now())

    assert {:ok, %{"anima" => @anima, "readings" => @readings}} = LiveState.read(path: path)
  end

  test "stale envelope is rejected" do
    dir = System.tmp_dir!()
    path = write_envelope(dir, NaiveDateTime.add(NaiveDateTime.local_now(), -120, :second))

    assert {:error, :stale} = LiveState.read(path: path)
  end

  test "missing and invalid files degrade cleanly" do
    assert {:error, :missing} = LiveState.read(path: "/nonexistent/nope.json")

    dir = System.tmp_dir!()
    bad = Path.join(dir, "bad_envelope.json")
    File.write!(bad, "{not json")
    assert {:error, :invalid} = LiveState.read(path: bad)
  end
end
