import type { ParamsDiff, ProtectedField } from "../api/types";

export interface ParamsReviewProps {
  params: ParamsDiff;
}

const PROTECTED_LABELS: Record<string, string> = {
  force_field: "力场",
  water_model: "水模型",
  topology: "拓扑",
};

function fieldInfo(
  params: ParamsDiff,
  field: string,
): ProtectedField | undefined {
  const lookup = params as unknown as Record<
    string,
    ProtectedField | undefined
  >;
  return lookup[field];
}

export function ParamsReview({ params }: ParamsReviewProps) {
  const protectedFields = params.protected_fields ?? [];
  return (
    <section className="params-review" data-testid="params-review">
      <h3>参数审阅</h3>
      {params.mdp.length > 0 && (
        <table className="mdp-diff" data-testid="mdp-diff">
          <thead>
            <tr>
              <th>参数</th>
              <th>默认</th>
              <th>当前</th>
              <th>差异</th>
            </tr>
          </thead>
          <tbody>
            {params.mdp.map((entry) => (
              <tr key={entry.key} data-testid={`mdp-${entry.key}`}>
                <td title={entry.explanation}>{entry.key}</td>
                <td>{entry.default}</td>
                <td>{entry.current ?? "—"}</td>
                <td>{entry.changed ? "已变更" : "未变更"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="protected" data-testid="protected-fields">
        <h4>受保护字段（只读）</h4>
        {protectedFields.map((field) => {
          const info = fieldInfo(params, field);
          const current = info?.current;
          return (
            <div
              key={field}
              className="protected-field"
              data-testid={`protected-${field}`}
            >
              <span className="field-name">
                {PROTECTED_LABELS[field] ?? field}
              </span>
              <span className="field-value">
                {current === undefined || current === null
                  ? "—"
                  : typeof current === "object"
                    ? JSON.stringify(current)
                    : String(current)}
              </span>
              <span
                className="field-note"
                data-testid={`protected-${field}-note`}
              >
                {info?.explanation ?? "变更需重新准备体系/交接。"}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
