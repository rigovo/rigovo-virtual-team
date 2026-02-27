import type { ApprovalItem, InboxTask } from "../../types";

type PolicySnapshot = {
  defaultTier: string;
  deepRigour: boolean;
  requireApprovalHighRisk: boolean;
  requireApprovalProdSecrets: boolean;
  notifyChannels: string[];
};

interface AutomationsPageProps {
  inbox: InboxTask[];
  approvals: ApprovalItem[];
  policy: PolicySnapshot | null;
}

export default function AutomationsPage({ inbox, approvals, policy }: AutomationsPageProps): JSX.Element {
  const activeTasks = inbox.filter((task) => {
    const status = task.status.toLowerCase();
    return !status.includes("complete") && !status.includes("fail") && !status.includes("reject");
  });
  const completedTasks = inbox.length - activeTasks.length;

  return (
    <section className="workspace-page">
      <div className="workspace-page-header">
        <h2>Automations</h2>
        <p>Live operational state from inbox, approvals, and governance policy APIs.</p>
      </div>

      <div className="workspace-grid">
        <article className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Queue health</h3>
              <p>From `GET /v1/ui/inbox` and `GET /v1/ui/approvals`</p>
            </div>
          </div>
          <p className="workspace-card-copy">
            Active tasks: <strong>{activeTasks.length}</strong> · Completed/failed: <strong>{completedTasks}</strong> · Pending approvals:{" "}
            <strong>{approvals.length}</strong>
          </p>
        </article>

        <article className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Policy snapshot</h3>
              <p>From `GET /v1/control/state` policy</p>
            </div>
          </div>
          {policy ? (
            <p className="workspace-card-copy">
              Default tier: <strong>{policy.defaultTier}</strong> · Deep rigour: <strong>{policy.deepRigour ? "on" : "off"}</strong> · High-risk
              approvals: <strong>{policy.requireApprovalHighRisk ? "on" : "off"}</strong> · Prod secret approvals:{" "}
              <strong>{policy.requireApprovalProdSecrets ? "on" : "off"}</strong>
            </p>
          ) : (
            <p className="workspace-card-copy">Policy API data unavailable.</p>
          )}
        </article>

        <article className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Notify channels</h3>
              <p>From `policy.notifyChannels`</p>
            </div>
          </div>
          <p className="workspace-card-copy">
            {policy?.notifyChannels?.length ? policy.notifyChannels.join(", ") : "No channels configured."}
          </p>
        </article>
      </div>
    </section>
  );
}
