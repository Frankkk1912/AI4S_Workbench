import type { ReceiptError } from "../api/types";

export interface HumanizedError {
  title: string;
  detail: string;
  suggestions: string[];
}

function summarize(text: string, max = 500): string {
  const first = text
    .split("\n")
    .slice(0, 6)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  return first.length > max ? `${first.slice(0, max)}…` : first;
}

/** Translate a failed receipt's returncode/stderr into human-readable text. */
export function humanizeError(receipt: ReceiptError): HumanizedError {
  const code = receipt.returncode;
  const stderr = (receipt.stderr ?? "").trim();
  if (code !== null && code !== undefined && code !== 0) {
    return {
      title: `任务失败（退出码 ${code}）`,
      detail: stderr ? summarize(stderr) : "未提供 stderr 摘要。",
      suggestions: [
        "查看实时日志定位错误。",
        "修正输入或科学参数后，填写原因并批准重试。",
        "若为 checkpoint 问题，可批准恢复而非重新运行。",
      ],
    };
  }
  return {
    title: "任务未成功完成",
    detail: stderr ? summarize(stderr) : "未提供失败详情。",
    suggestions: [
      "查看实时日志与阶段状态。",
      "若状态为 failed，可填写原因后批准重试。",
    ],
  };
}
