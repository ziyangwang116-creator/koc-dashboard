"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, ChevronDown, Database, FileSpreadsheet, Loader2, Paperclip, Plus, Send, ShieldCheck, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AgentVisualization } from "@/components/AgentVisualization";
import { AppShell } from "@/components/AppShell";
import { ErrorState, LoadingState } from "@/components/DataStates";
import { ApiError } from "@/lib/api-client";
import { agentApi, importsApi } from "@/lib/endpoints";
import type { AgentMessage, AgentPendingAction } from "@/lib/types";

const STORAGE_KEY = "koc-agent-conversation-id";
const SUGGESTIONS = [
  "分析 2026-07 整体运营表现",
  "哪些达人播放量环比下降超过 30%",
  "查看某达人 2026-07 的投稿和播放量",
  "列出 2026-07 YouTube 播放量 Top 10 视频",
  "审计 2026-07 数据是否存在异常",
];

export default function AgentPage() {
  const queryClient = useQueryClient();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [localMessages, setLocalMessages] = useState<AgentMessage[] | null>(null);
  const [input, setInput] = useState("");
  const [attachment, setAttachment] = useState<File | null>(null);
  const [restored, setRestored] = useState(false);
  const streamEndRef = useRef<HTMLDivElement>(null);
  const attachmentInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setConversationId(window.localStorage.getItem(STORAGE_KEY));
      setRestored(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const statusQuery = useQuery({
    queryKey: ["agent", "status"],
    queryFn: () => agentApi.status(),
  });

  const messagesQuery = useQuery({
    queryKey: ["agent", "messages", conversationId],
    queryFn: () => agentApi.messages(conversationId as string),
    enabled: restored && Boolean(conversationId),
    retry: false,
  });

  const conversationMissing =
    (messagesQuery.error as ApiError | undefined)?.code === "CONVERSATION_NOT_FOUND";
  const activeConversationId = conversationMissing ? null : conversationId;
  const messages = useMemo(
    () => localMessages ?? (conversationMissing ? [] : messagesQuery.data?.data ?? []),
    [conversationMissing, localMessages, messagesQuery.data]
  );

  useEffect(() => {
    if (typeof streamEndRef.current?.scrollIntoView === "function") {
      streamEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages]);

  const sendMutation = useMutation({
    mutationFn: async ({ message, file }: { message: string; file: File | null }) => {
      let activeId = activeConversationId;
      if (!activeId) {
        const created = await agentApi.createConversation();
        activeId = created.data.conversation_id;
        setConversationId(activeId);
        window.localStorage.setItem(STORAGE_KEY, activeId);
      }
      let modelMessage = message;
      if (file) {
        const preview = await importsApi.preview([file]);
        const data = preview.data;
        if (data.unmatched_creators.count > 0) {
          throw new Error(`文件存在 ${data.unmatched_creators.count} 条未匹配达人，已停止导入。`);
        }
        modelMessage = `${message || "请导入这份投稿数据"}\n\n` +
          `[系统已完成 Excel 导入预览，请调用 import_posts_from_preview。\n` +
          `preview_token=${data.preview_token}\n` +
          `period_months=${data.period_months.join(",")}\n` +
          `input_row_count=${data.input_row_count}\n` +
          `matched_row_count=${data.matched_row_count}\n` +
          `支持按月份完整替换或补充导入/更新；如果用户没有说明模式，请先询问。]`;
      }
      return agentApi.sendMessage(activeId, modelMessage);
    },
    onSuccess: (response) => {
      setLocalMessages((current) => {
        const next = [
          ...(current ?? messages),
          {
            role: "assistant" as const,
            content: response.data.answer,
            tool_calls: response.data.tool_calls,
            visualizations: response.data.visualizations,
            pending_actions: response.data.pending_actions,
          },
        ];
        queryClient.setQueryData(
          ["agent", "messages", response.data.conversation_id],
          { data: next }
        );
        return next;
      });
    },
  });

  const confirmActionMutation = useMutation({
    mutationFn: ({ actionId, approve }: { actionId: string; approve: boolean }) => {
      if (!activeConversationId) throw new Error("对话不存在。");
      return agentApi.confirmAction(activeConversationId, actionId, approve);
    },
    onSuccess: (response, variables) => {
      setLocalMessages((current) =>
        (current ?? messages).map((message) => ({
          ...message,
          pending_actions: message.pending_actions?.filter(
            (action) => action.action_id !== variables.actionId,
          ),
        })),
      );
      queryClient.invalidateQueries({ queryKey: ["creators"] });
      queryClient.invalidateQueries({ queryKey: ["compensation"] });
      const statusText = response.data.status === "executed" ? "已确认执行" : "已取消操作";
      setLocalMessages((current) => [
        ...(current ?? messages),
        { role: "assistant", content: `${statusText}。` },
      ]);
    },
  });

  async function createNewConversation() {
    const response = await agentApi.createConversation();
    setConversationId(response.data.conversation_id);
    window.localStorage.setItem(STORAGE_KEY, response.data.conversation_id);
    setLocalMessages([]);
    setInput("");
    clearAttachment();
  }

  function clearAttachment() {
    setAttachment(null);
    if (attachmentInputRef.current) attachmentInputRef.current.value = "";
  }

  function submitMessage(message: string) {
    const cleaned = message.trim();
    if ((!cleaned && !attachment) || sendMutation.isPending) return;
    const file = attachment;
    const displayMessage = file
      ? `${cleaned || "导入投稿数据"}\n\n附件：${file.name}`
      : cleaned;
    setLocalMessages([...messages, { role: "user", content: displayMessage }]);
    setInput("");
    clearAttachment();
    sendMutation.mutate({ message: cleaned, file });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitMessage(input);
  }

  const status = statusQuery.data?.data;
  const error = sendMutation.error as ApiError | null;

  return (
    <AppShell>
      <section className="agent-page">
        <header className="agent-header">
          <div>
            <h1>运营 Agent</h1>
            <p>查询达人、投稿、合同、排行与已保存的结算数据</p>
          </div>
          <div className="agent-header-actions">
            {status && (
              <>
                <span className="agent-badge">{status.provider_label} · {status.model}</span>
                <span className="agent-badge agent-badge-readonly">
                  <ShieldCheck size={14} />可执行，写入需确认
                </span>
              </>
            )}
            <button
              type="button"
              className="agent-icon-button"
              aria-label="新建对话"
              title="新建对话"
              onClick={createNewConversation}
            >
              <Plus size={17} />
            </button>
          </div>
        </header>

        {statusQuery.isLoading && <LoadingState label="检查 Agent 配置..." />}
        {statusQuery.isError && <ErrorState message="Agent 状态加载失败，请稍后重试。" />}
        {status && !status.configured && (
          <ErrorState message="Agent 尚未配置，请联系管理员检查 Railway 环境变量。" />
        )}

        <div className="agent-workspace">
          <aside className="agent-suggestions" aria-label="推荐问题">
            <div className="agent-section-title">常用运营问题</div>
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => submitMessage(suggestion)}
                disabled={!status?.configured || sendMutation.isPending}
              >
                {suggestion}
              </button>
            ))}
            <div className="agent-scope-note">
              <Database size={15} />
              <span>数据来自当前达人库、投稿明细和已保存结算版本。</span>
            </div>
          </aside>

          <div className="agent-chat">
            <div className="agent-stream" aria-live="polite">
              {messagesQuery.isLoading ? (
                <LoadingState label="恢复对话..." />
              ) : messages.length === 0 ? (
                <div className="agent-empty">
                  <Bot size={28} />
                  <strong>从一个运营问题开始</strong>
                  <span>请写明月份与达人名称，查询会更准确。</span>
                </div>
              ) : (
                messages.map((message, index) => (
                  <article
                    key={`${message.role}-${index}`}
                    className={`agent-message agent-message-${message.role}`}
                  >
                    <div className="agent-message-role">
                      {message.role === "user" ? "你" : "运营 Agent"}
                    </div>
                    <div className="agent-message-content agent-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {message.content}
                      </ReactMarkdown>
                    </div>
                    {message.visualizations?.map((chart) => (
                      <AgentVisualization key={chart.id} chart={chart} />
                    ))}
                    {message.pending_actions?.map((action) => (
                      <PendingActionCard
                        key={action.action_id}
                        action={action}
                        disabled={confirmActionMutation.isPending}
                        onConfirm={(approve) =>
                          confirmActionMutation.mutate({
                            actionId: action.action_id,
                            approve,
                          })
                        }
                      />
                    ))}
                    {message.tool_calls && message.tool_calls.length > 0 && (
                      <details className="agent-evidence">
                        <summary><ChevronDown size={14} />查询依据</summary>
                        {message.tool_calls.map((tool, toolIndex) => (
                          <div key={`${tool.tool_name}-${toolIndex}`} className="agent-evidence-row">
                            <code>{tool.tool_name}</code>
                            <span>{JSON.stringify(tool.summary)}</span>
                          </div>
                        ))}
                      </details>
                    )}
                  </article>
                ))
              )}
              {sendMutation.isPending && (
                <div className="agent-thinking" role="status">
                  <Loader2 className="spin" size={16} />正在核对数据库...
                </div>
              )}
              {error && <ErrorState message={error.message} />}
              <div ref={streamEndRef} />
            </div>

            <form className="agent-composer" onSubmit={handleSubmit}>
              <input
                ref={attachmentInputRef}
                type="file"
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                className="agent-file-input"
                aria-label="上传投稿 Excel"
                onChange={(event) => setAttachment(event.target.files?.[0] ?? null)}
              />
              {attachment && (
                <div className="agent-attachment">
                  <FileSpreadsheet size={15} />
                  <span>{attachment.name}</span>
                  <button
                    type="button"
                    aria-label="移除附件"
                    title="移除附件"
                    onClick={clearAttachment}
                  >
                    <X size={14} />
                  </button>
                </div>
              )}
              <button
                type="button"
                className="agent-attach-button"
                aria-label="上传投稿 Excel"
                title="上传投稿 Excel"
                onClick={() => attachmentInputRef.current?.click()}
                disabled={!status?.configured || sendMutation.isPending}
              >
                <Paperclip size={17} />
              </button>
              <textarea
                aria-label="向运营 Agent 提问"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submitMessage(input);
                  }
                }}
                placeholder="例如：查看白黑女神 2026-07 的投稿和播放量"
                maxLength={4000}
                disabled={!status?.configured || sendMutation.isPending}
              />
              <button
                type="submit"
                aria-label="发送问题"
                title="发送问题"
                disabled={(!input.trim() && !attachment) || !status?.configured || sendMutation.isPending}
              >
                <Send size={17} />
              </button>
            </form>
          </div>
        </div>
      </section>
    </AppShell>
  );
}

function PendingActionCard({
  action,
  disabled,
  onConfirm,
}: {
  action: AgentPendingAction;
  disabled: boolean;
  onConfirm: (approve: boolean) => void;
}) {
  const preview = action.preview;
  const diff = typeof preview.diff === "string" ? preview.diff : null;
  return (
    <div className="agent-pending-action">
      <div className="agent-pending-action-title">
        <strong>待确认操作</strong>
        <code>{action.tool_name}</code>
      </div>
      {diff ? (
        <pre className="agent-pending-diff">{diff}</pre>
      ) : (
        <pre className="agent-pending-diff">
          {JSON.stringify(preview, null, 2)}
        </pre>
      )}
      <div className="agent-pending-action-buttons">
        <button type="button" disabled={disabled} onClick={() => onConfirm(true)}>
          <Check size={14} />确认执行
        </button>
        <button type="button" disabled={disabled} onClick={() => onConfirm(false)}>
          <X size={14} />取消
        </button>
      </div>
    </div>
  );
}
