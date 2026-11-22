import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

function App() {
  const [player, setPlayer] = useState(null);
  const [state, setState] = useState(null);
  const [result, setResult] = useState(null);
  const [text, setText] = useState("");
  const [candidate, setCandidate] = useState("");
  const [joining, setJoining] = useState(false);
  const [connected, setConnected] = useState(false);
  const [votePending, setVotePending] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const socket = useRef(null);

  useEffect(() => {
    return () => {
      if (socket.current) {
        socket.current.onclose = null;
        socket.current.close();
      }
    };
  }, []);

  useEffect(() => {
    if (!state?.discussion_ends_at) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [state?.discussion_ends_at]);

  useEffect(() => {
    setText("");
    setCandidate("");
  }, [state?.round]);

  async function join() {
    setJoining(true);
    setError("");
    try {
      const response = await fetch("/join", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.detail || "Unable to join the experiment.");
      }
      const { player: label, participant_token: token } = await response.json();
      setPlayer(label);
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const connection = new WebSocket(
        `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`
      );
      socket.current = connection;
      connection.onopen = () => setConnected(true);
      connection.onmessage = ({ data }) => {
        let event;
        try {
          event = JSON.parse(data);
        } catch {
          setVotePending(false);
          setError("Received an invalid update from the experiment.");
          return;
        }
        if (event.type === "state") {
          setState(event);
          setVotePending(false);
        } else if (event.type === "message") {
          setState((previous) => ({
            ...previous,
            messages: [...previous.messages, event],
          }));
        } else if (event.type === "result") {
          setResult(event);
        } else if (event.type === "error") {
          setVotePending(false);
          setError(event.message);
        }
      };
      connection.onclose = () => {
        setConnected(false);
        setVotePending(false);
        setError("Connection to the experiment was lost.");
      };
      connection.onerror = () => setError("Unable to connect to the experiment.");
    } catch (failure) {
      setError(failure.message || "Unable to join the experiment.");
    } finally {
      setJoining(false);
    }
  }

  function send(event) {
    if (socket.current?.readyState !== WebSocket.OPEN) {
      setError("Connection to the experiment was lost.");
      return false;
    }
    try {
      socket.current.send(JSON.stringify(event));
    } catch {
      setError("Unable to send the event.");
      return false;
    }
    setError("");
    return true;
  }

  const remaining = state?.discussion_ends_at
    ? Math.max(0, Math.ceil((Date.parse(state.discussion_ends_at) - now) / 1000))
    : 0;

  return (
    <main>
      <header>
        <h1>Experiment platform</h1>
        {player && <p>You are Player {player}.</p>}
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {!player ? (
        <section>
          <h2>Waiting room</h2>
          <p>The experiment begins when all participants have joined.</p>
          <button onClick={join} disabled={joining}>
            {joining ? "Joining..." : "Join experiment"}
          </button>
        </section>
      ) : !state ? (
        <p>{error ? "Unable to connect to the experiment." : "Connecting to the experiment..."}</p>
      ) : state.phase === "waiting" ? (
        <section>
          <h2>Waiting room</h2>
          <p>Waiting for the experiment to begin.</p>
        </section>
      ) : state.phase === "discussion" ? (
        <section>
          <h2>Discussion: round {state.round}</h2>
          <p>Time remaining: {remaining} seconds</p>
          <div className="conversation" aria-label="Discussion messages" aria-live="polite">
            {state.messages.map((message, index) => (
              <p key={index}>
                <strong>Round {message.round} - Player {message.sender}:</strong> {message.text}
              </p>
            ))}
          </div>
          <form onSubmit={(event) => {
            event.preventDefault();
            if (send({ type: "message", round: state.round, text })) setText("");
          }}>
            <label htmlFor="message">Message</label>
            <textarea id="message" value={text} onChange={(event) => setText(event.target.value)} />
            <button type="submit" disabled={!connected}>Send</button>
          </form>
        </section>
      ) : state.phase === "voting" ? (
        <section>
          <h2>Vote: round {state.round}</h2>
          {state.has_voted ? <p>Waiting for the other votes.</p> : (
            <form onSubmit={(event) => {
              event.preventDefault();
              if (send({ type: "vote", candidate })) setVotePending(true);
            }}>
              <label htmlFor="candidate">Choose the Decision Maker</label>
              <select id="candidate" value={candidate} onChange={(event) => setCandidate(event.target.value)}
                disabled={!connected || votePending}>
                <option value="">Select a player</option>
                {state.players.map((label) => <option key={label} value={label}>Player {label}</option>)}
              </select>
              <button type="submit" disabled={!connected || votePending || !candidate}>Submit vote</button>
            </form>
          )}
        </section>
      ) : (
        <section>
          <h2>Results</h2>
          {result ? (
            <>
              <p>Decision Maker: Player {result.decision_maker}</p>
              {state.players.map((label) => (
                <p key={label}>Player {label}: {result.vote_counts[label]} votes</p>
              ))}
            </>
          ) : <p>Waiting for results...</p>}
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
