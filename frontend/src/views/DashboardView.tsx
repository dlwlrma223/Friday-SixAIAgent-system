import { useEffect } from "react";
import { initDashboard } from "./dashboard";
import "../css/dashboard.css";

function DashboardView() {
  useEffect(() => {
    const cleanup = initDashboard();
    return cleanup;
  }, []);

  return (
    <div className="wrap">
      <div className="topbar">
        <div className="brand">
          <div className="brand-mark">CS</div>
          <div className="brand-text">
            <h1>Friday</h1>
            <p>Personal AI Team · Live Console</p>
          </div>
        </div>
        <div className="top-meta">
          <div className="meta-item">
            <div className="label">Local Time</div>
            <div className="value" id="clock">--:--:--</div>
          </div>
          <div className="meta-item">
            <div className="label">Agents Active</div>
            <div className="value">6 / 6</div>
          </div>
          <div className="status-pill">
            <span className="status-dot"></span>All Systems Nominal
          </div>
        </div>
      </div>

      <div className="main-grid">
        <div className="panel">
          <div className="panel-head">
            <h2>Field Map — Life Domains</h2>
            <span className="count">6 clusters · 42 nodes</span>
          </div>
          <div className="field-wrap">
            <canvas id="fieldCanvas"></canvas>
            <div className="field-legend">
              <div><span className="tag">●</span> node — active task or thread</div>
              <div><span className="tag">—</span> line — information passed between agents</div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>Needs Your Approval</h2>
            <span className="count" id="approvalCount">4 pending</span>
          </div>
          <div className="approvals-list" id="approvalsList"></div>
          <div className="panel-head" style={{ borderTop: "1px solid var(--line)" }}>
            <h2>Today at a Glance</h2>
          </div>
          <div className="glance">
            <div className="glance-stat"><div className="num">3</div><div className="lbl">Jobs applied to</div></div>
            <div className="glance-stat"><div className="num">3</div><div className="lbl">Meetings scheduled</div></div>
            <div className="glance-stat"><div className="num">45<small>m</small></div><div className="lbl">Study time logged</div></div>
            <div className="glance-stat"><div className="num">5<small>/6</small></div><div className="lbl">Tasks closed out</div></div>
          </div>
        </div>
      </div>

      <div className="bottom-grid">
        <div className="panel">
          <div className="panel-head"><h2>Run Log</h2><span className="count">live</span></div>
          <div className="log-feed" id="logFeed"></div>
        </div>

        <div className="panel">
          <div className="panel-head"><h2>Task Queue</h2><span className="count" id="queueCount">7 open</span></div>
          <div className="queue-list" id="queueList"></div>
        </div>

        <div className="panel">
          <div className="panel-head"><h2>Agent Roster</h2></div>
          <div className="roster" id="roster"></div>
        </div>

        <div className="panel focus-panel">
          <div className="gauge-wrap">
            <svg viewBox="0 0 120 120" width="120" height="120">
              <circle cx="60" cy="60" r="52" fill="none" stroke="var(--line)" strokeWidth="8" />
              <circle
                id="gaugeArc"
                cx="60"
                cy="60"
                r="52"
                fill="none"
                stroke="var(--amber)"
                strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray="326.7"
                strokeDashoffset="326.7"
                transform="rotate(-90 60 60)"
              />
            </svg>
            <div className="gauge-num"><div className="n" id="gaugeNum">0%</div><div className="u">capacity</div></div>
          </div>
          <div className="focus-caption">Team is at comfortable load. Room for 2 more requests today.</div>
        </div>
      </div>
    </div>
  );
}

export default DashboardView;
