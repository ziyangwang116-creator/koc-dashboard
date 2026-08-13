"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, Database, Loader2, Plus, Send, ShieldCheck } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AgentVisualization } from "@/components/AgentVisualization";
import { AppShell } from "@/components/AppShell";
import { ErrorState, LoadingState } from "@/components/DataStates";
import { ApiError } from "@/lib/api-client";
import { agentApi } from "@/lib/endpoints";
import type { AgentMessage } from "@/lib/types";

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
  const [restored, setRestored] = useState(false);
  const streamEndRef = useRef<HTMLDivElement>(null);

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
    mutationFn: async (message: string) => {
      let activeId = activeConversationId;
      if (!activeId) {
        const created = await agentApi.createConversation();
        activeId = created.data.conversation_id;
        setConversationId(activeId);
        window.localStorage.setItem(STORAGE_KEY, activeId);
      }
      return agentApi.sendMessage(activeId, message);
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

  async function createNewConversation() {
    const response = await agentApi.createConversation();
    setConversationId(response.data.conversation_id);
    window.localStorage.setItem(STORAGE_KEY, response.data.conversation_id);
    setLocalMessages([]);
    setInput("");
  }

  function submitMessage(message: string) {
    const cleaned = message.trim();
    if (!cleaned || sendMutation.isPending) return;
    setLocalMessages([...messages, { role: "user", content: cleaned }]);
    setInput("");
    sendMutation.mutate(cleaned);
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
                  <ShieldCheck size={14} />只读模式
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
                disabled={!input.trim() || !status?.configured || sendMutation.isPending}
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
