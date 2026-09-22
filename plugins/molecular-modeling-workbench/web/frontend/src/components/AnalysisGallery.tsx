import { useState } from "react";
import type {
  AnalysisExportFormat,
  AnalysisSession,
  AnalysisStyle,
} from "../api/types";

export interface AnalysisGalleryProps {
  sessions: AnalysisSession[];
  canApprove: boolean;
  previewUrls?: Record<string, string>;
  onApprove: () => void | Promise<void>;
  onRestyle: (sessionId: string, style: AnalysisStyle) => void | Promise<void>;
  onExport: (
    sessionId: string,
    format: AnalysisExportFormat,
  ) => void | Promise<void>;
}

const FORMATS: AnalysisExportFormat[] = ["png", "svg", "pdf"];
const DEFAULT_STYLE: AnalysisStyle = {
  colors: { system: "#4a90e2", comparison: "#e95c4b" },
  font_family: "sans-serif",
  font_size: 8,
  fig_size: [6.8, 7.5],
  style_schema_version: "1.0",
};

export function AnalysisGallery({
  sessions,
  canApprove,
  previewUrls = {},
  onApprove,
  onRestyle,
  onExport,
}: AnalysisGalleryProps) {
  const [style, setStyle] = useState<AnalysisStyle>(DEFAULT_STYLE);

  return (
    <section className="analysis-gallery" data-testid="analysis-gallery">
      <div className="gallery-heading">
        <div>
          <h3>分析结果画廊</h3>
          <p>
            正式结果仅来自 completed
            阶段或后端冻结快照；实时监控不作为分析结果。
          </p>
        </div>
        <button
          type="button"
          data-testid="approve-analysis"
          disabled={!canApprove}
          onClick={() => onApprove()}
        >
          批准并提交分析
        </button>
      </div>
      {sessions.length === 0 ? (
        <p data-testid="analysis-empty">尚无分析会话</p>
      ) : (
        <ul className="analysis-sessions">
          {sessions.map((session) => (
            <li
              key={session.session_id}
              data-testid={`analysis-${session.session_id}`}
            >
              <div>
                <strong>{session.session_id}</strong>{" "}
                <span className="badge status">{session.status}</span>
              </div>
              <p>
                来源：
                {session.source_kind === "completed"
                  ? "已完成阶段"
                  : "后端冻结快照"}
                ；stage：{session.source_stage}
              </p>
              <p>
                图中汇总温度、压力、势能、RMSD 与
                RMSF；重绘只改变配色、字体和图幅， 不重新计算数值。
              </p>
              <p className="data-reference">
                数据引用：xtc {session.science.xtc_sha256.slice(0, 12)}… · group{" "}
                {session.science.group} · {session.science.begin_ps ?? "起点"}–
                {session.science.end_ps ?? "终点"} ps
              </p>
              {previewUrls[session.session_id] && (
                <img
                  className="analysis-preview"
                  data-testid={`preview-${session.session_id}`}
                  src={previewUrls[session.session_id]}
                  alt={`${session.session_id} 诊断图`}
                />
              )}
              <fieldset className="style-controls">
                <legend>仅重绘样式</legend>
                <label>
                  主色
                  <input
                    aria-label="主色"
                    type="color"
                    value={style.colors.system ?? "#4a90e2"}
                    onChange={(event) =>
                      setStyle({
                        ...style,
                        colors: { ...style.colors, system: event.target.value },
                      })
                    }
                  />
                </label>
                <label>
                  对比色
                  <input
                    aria-label="对比色"
                    type="color"
                    value={style.colors.comparison ?? "#e95c4b"}
                    onChange={(event) =>
                      setStyle({
                        ...style,
                        colors: {
                          ...style.colors,
                          comparison: event.target.value,
                        },
                      })
                    }
                  />
                </label>
                <label>
                  字体
                  <select
                    aria-label="字体"
                    value={style.font_family}
                    onChange={(event) =>
                      setStyle({ ...style, font_family: event.target.value })
                    }
                  >
                    <option value="sans-serif">Sans serif</option>
                    <option value="serif">Serif</option>
                    <option value="monospace">Monospace</option>
                  </select>
                </label>
                <label>
                  字号
                  <input
                    aria-label="字号"
                    type="number"
                    min="1"
                    max="72"
                    step="0.5"
                    value={style.font_size}
                    onChange={(event) =>
                      setStyle({
                        ...style,
                        font_size: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  宽度
                  <input
                    aria-label="宽度"
                    type="number"
                    min="1"
                    max="100"
                    step="0.1"
                    value={style.fig_size[0]}
                    onChange={(event) =>
                      setStyle({
                        ...style,
                        fig_size: [
                          Number(event.target.value),
                          style.fig_size[1],
                        ],
                      })
                    }
                  />
                </label>
                <label>
                  高度
                  <input
                    aria-label="高度"
                    type="number"
                    min="1"
                    max="100"
                    step="0.1"
                    value={style.fig_size[1]}
                    onChange={(event) =>
                      setStyle({
                        ...style,
                        fig_size: [
                          style.fig_size[0],
                          Number(event.target.value),
                        ],
                      })
                    }
                  />
                </label>
                <button
                  type="button"
                  data-testid={`restyle-${session.session_id}`}
                  disabled={session.status !== "completed"}
                  onClick={() => onRestyle(session.session_id, style)}
                >
                  批准样式并重绘
                </button>
              </fieldset>
              <div className="export-actions">
                {FORMATS.map((format) => (
                  <button
                    key={format}
                    type="button"
                    disabled={!session.exports[format]}
                    data-testid={`export-${session.session_id}-${format}`}
                    onClick={() => onExport(session.session_id, format)}
                  >
                    {format.toUpperCase()}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
