/** 图形调度是系统编辑页，不伪装成可执行的游戏任务。 */
export const SCHEDULER_EDITOR = 'SchedulerProgram'
export function taskNavItems(key: string | null, tasks: string[]) {
  return key === 'Alas' ? [tasks[0]!, SCHEDULER_EDITOR, ...tasks.slice(1)] : tasks
}
