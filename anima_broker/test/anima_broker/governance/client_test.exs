defmodule AnimaBroker.Governance.ClientTest do
  # Not async: exercises the shared State.Store.
  use ExUnit.Case, async: false

  alias AnimaBroker.Governance.Client
  alias AnimaBroker.State.Store

  @onboard_result %{
    "uuid" => "test-uuid-1234",
    "client_session_id" => "agent-test-1234",
    "agent_id" => "TestAgent"
  }

  defp fresh_live_envelope!(name) do
    path = Path.join(System.tmp_dir!(), name)

    File.write!(
      path,
      Jason.encode!(%{
        "updated_at" => NaiveDateTime.to_iso8601(NaiveDateTime.local_now()),
        "pid" => 1,
        "data" => %{
          "anima" => %{
            "warmth" => 0.4,
            "clarity" => 0.8,
            "stability" => 0.7,
            "presence" => 0.6
          },
          "readings" => %{"ambient_temp_c" => 24.5, "cpu_percent" => 10.0}
        }
      })
    )

    path
  end

  defp start_client(http_post, extra_opts \\ []) do
    live = fresh_live_envelope!("client_test_live_#{System.unique_integer([:positive])}.json")

    id_file =
      Path.join(System.tmp_dir!(), "gov_id_#{System.unique_integer([:positive])}.json")

    opts =
      [
        name: nil,
        url: "http://localhost:9/v1/tools/call",
        interval_ms: 3_600_000,
        http_post: http_post,
        id_file: id_file,
        live_state_opts: [path: live]
      ] ++ extra_opts

    {:ok, pid} = GenServer.start_link(Client, opts)
    %{pid: pid, id_file: id_file, live: live}
  end

  defp ok_envelope(result),
    do: {:ok, 200, Jason.encode!(%{"success" => true, "result" => result})}

  test "onboards, echoes csid on check-in, writes governance slice to the Store" do
    me = self()

    http_post = fn _url, body, _headers, _timeout ->
      send(me, {:post, body})

      case body["name"] do
        "onboard" ->
          ok_envelope(@onboard_result)

        "process_agent_update" ->
          ok_envelope(%{"action" => "proceed", "margin" => "comfortable", "reason" => "ok"})
      end
    end

    %{pid: pid, id_file: id_file} = start_client(http_post)

    assert_receive {:post, %{"name" => "onboard", "arguments" => onboard_args}}, 2_000
    assert onboard_args["force_new"] == true
    assert onboard_args["name"] == "lumen-broker-ex-shadow"

    send(pid, :checkin)
    assert_receive {:post, %{"name" => "process_agent_update", "arguments" => args}}, 2_000

    # Strict identity: the onboard-echoed CSID must ride in arguments.
    assert args["client_session_id"] == "agent-test-1234"
    assert args["agent_name"] == "lumen-broker-ex"
    assert args["response_mode"] == "minimal"
    assert is_number(args["complexity"]) and is_number(args["confidence"])
    assert [_, _, _] = args["ethical_drift"]
    assert %{"eisv" => %{"E" => _}} = args["sensor_data"]

    # Governance decision landed in the (shadow) Store slice.
    wait_until(fn -> get_in(Store.snapshot(), ["governance", "action"]) == "proceed" end)
    gov = Store.snapshot()["governance"]
    assert gov["source"] == "unitares_ex"
    assert gov["identity_mode"] == "scratch"
    assert gov["unitares_agent_id"] == "test-uuid-1234"
    assert is_binary(gov["governance_at"])

    # Identity persisted for parent chaining across restarts.
    assert %{"agent_uuid" => "test-uuid-1234"} = Jason.decode!(File.read!(id_file))
  end

  test "prior uuid is declared as parent_agent_id on re-onboard" do
    me = self()
    id_file = Path.join(System.tmp_dir!(), "gov_id_#{System.unique_integer([:positive])}.json")
    File.write!(id_file, Jason.encode!(%{"agent_uuid" => "prior-uuid-999"}))

    http_post = fn _url, body, _headers, _timeout ->
      send(me, {:post, body})
      ok_envelope(@onboard_result)
    end

    live = fresh_live_envelope!("client_test_live_#{System.unique_integer([:positive])}.json")

    {:ok, _pid} =
      GenServer.start_link(Client,
        name: nil,
        url: "http://localhost:9/v1/tools/call",
        interval_ms: 3_600_000,
        http_post: http_post,
        id_file: id_file,
        live_state_opts: [path: live]
      )

    assert_receive {:post, %{"name" => "onboard", "arguments" => args}}, 2_000
    assert args["parent_agent_id"] == "prior-uuid-999"
  end

  test "breaker opens after 2 consecutive failures and blocks the next attempt" do
    me = self()
    {:ok, agent} = Agent.start_link(fn -> 0 end)

    http_post = fn _url, body, _headers, _timeout ->
      case body["name"] do
        "onboard" ->
          ok_envelope(@onboard_result)

        "process_agent_update" ->
          Agent.update(agent, &(&1 + 1))
          send(me, {:checkin_attempt, Agent.get(agent, & &1)})
          {:error, :econnrefused}
      end
    end

    %{pid: pid} = start_client(http_post)
    # wait for onboard to complete
    wait_until(fn -> :sys.get_state(pid).identity != nil end)

    send(pid, :checkin)
    assert_receive {:checkin_attempt, 1}, 2_000
    send(pid, :checkin)
    assert_receive {:checkin_attempt, 2}, 2_000

    # Breaker now open (2 consecutive failures): the third tick is skipped.
    send(pid, :checkin)
    refute_receive {:checkin_attempt, 3}, 300

    state = :sys.get_state(pid)
    assert state.failures == 2
    assert state.blocked_until_ms > System.monotonic_time(:millisecond)
  end

  test "AGENT_PAUSED is recorded as a pause decision, not a breaker trip" do
    me = self()

    http_post = fn _url, body, _headers, _timeout ->
      case body["name"] do
        "onboard" ->
          ok_envelope(@onboard_result)

        "process_agent_update" ->
          send(me, :checkin_attempt)

          {:ok, 200,
           Jason.encode!(%{
             "success" => false,
             "error_code" => "AGENT_PAUSED",
             "error" => "paused pending review"
           })}
      end
    end

    %{pid: pid} = start_client(http_post)
    wait_until(fn -> :sys.get_state(pid).identity != nil end)

    send(pid, :checkin)
    assert_receive :checkin_attempt, 2_000

    wait_until(fn -> get_in(Store.snapshot(), ["governance", "action"]) == "pause" end)
    assert :sys.get_state(pid).failures == 0
  end

  test "fixed csid mode skips onboard and claims the substrate identity" do
    me = self()

    http_post = fn _url, body, _headers, _timeout ->
      send(me, {:post, body})
      ok_envelope(%{"action" => "proceed"})
    end

    %{pid: pid} = start_client(http_post, fixed_csid: "lumen-substrate-csid")

    send(pid, :checkin)
    assert_receive {:post, %{"name" => "process_agent_update", "arguments" => args}}, 2_000
    assert args["client_session_id"] == "lumen-substrate-csid"
    assert args["agent_name"] == "Lumen"
    refute_received {:post, %{"name" => "onboard"}}
  end

  test "does not start when no url is configured" do
    assert :ignore = GenServer.start_link(Client, name: nil, url: nil)
  end

  defp wait_until(fun, tries \\ 40) do
    cond do
      fun.() ->
        :ok

      tries == 0 ->
        flunk("condition never became true")

      true ->
        Process.sleep(50)
        wait_until(fun, tries - 1)
    end
  end
end
