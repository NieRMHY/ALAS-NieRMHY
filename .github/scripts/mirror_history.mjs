import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

// 与 GitCode 同步脚本共用固定基线，避免两套生成器产生不同的镜像 SHA。
export const MIRROR_BASELINE = JSON.parse(
  fs.readFileSync(new URL("./mirror_history.json", import.meta.url), "utf8"),
).baseline;

export class MirrorHistoryIncompleteError extends Error {}

function git(repoRoot, args, input) {
  const result = spawnSync("git", args, { cwd: repoRoot, input, maxBuffer: 64 * 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(result.stderr.toString("utf8"));
  return result.stdout;
}

export function rewriteCommit(raw, mapping) {
  const separator = raw.indexOf("\n\n");
  if (separator < 0) throw new Error("提交对象缺少正文分隔符");
  // latin1 往返保留作者、编码等头部原始字节，正文保持 Buffer 不解码。
  const result = [];
  let skip = false;
  for (const line of raw.subarray(0, separator).toString("latin1").split("\n")) {
    if (line.startsWith(" ")) {
      if (!skip) result.push(line);
      continue;
    }
    const key = line.split(" ", 1)[0];
    skip = ["gpgsig", "gpgsig-sha256", "mergetag"].includes(key);
    if (key === "parent") {
      const parent = mapping.get(line.slice(7));
      if (parent) result.push(`parent ${parent}`);
    } else if (!skip) {
      result.push(line);
    }
  }
  return Buffer.concat([Buffer.from(`${result.join("\n")}\n\n`, "latin1"), raw.subarray(separator + 2)]);
}

export function buildMirrorMapping(repoRoot, latest, baseline = MIRROR_BASELINE) {
  const reachable = new Set(git(repoRoot, ["rev-list", latest]).toString("ascii").trim().split("\n"));
  const isShallow = git(repoRoot, ["rev-parse", "--is-shallow-repository"]).toString("ascii").trim() === "true";
  if (!reachable.has(baseline)) {
    if (isShallow) throw new MirrorHistoryIncompleteError("浅克隆尚未读到镜像固定基线");
    return null;
  }
  const shallowPath = git(repoRoot, ["rev-parse", "--git-path", "shallow"]).toString("utf8").trim();
  // 基线后的侧支也必须完整；缺失对象时拒绝生成错误 SHA。
  const boundaries = isShallow
    ? fs.readFileSync(path.resolve(repoRoot, shallowPath), "ascii").trim().split("\n")
    : [];
  for (const boundary of boundaries.filter((commit) => reachable.has(commit))) {
    const check = spawnSync("git", ["merge-base", "--is-ancestor", boundary, baseline], { cwd: repoRoot });
    if (check.error) throw check.error;
    if (check.status === 1) throw new MirrorHistoryIncompleteError("浅克隆尚未完整覆盖镜像固定基线");
    if (check.status !== 0) throw new Error(check.stderr.toString("utf8"));
  }
  const descendants = git(repoRoot, [
    "rev-list", "--ancestry-path", "--topo-order", "--reverse", `${baseline}..${latest}`,
  ]).toString("ascii").trim().split("\n").filter(Boolean);
  const mapping = new Map();
  for (const commit of [baseline, ...descendants]) {
    const raw = git(repoRoot, ["cat-file", "commit", commit]);
    const rewritten = rewriteCommit(raw, mapping);
    mapping.set(commit, git(repoRoot, ["hash-object", "-t", "commit", "-w", "--stdin"], rewritten).toString("ascii").trim());
  }
  return mapping;
}
