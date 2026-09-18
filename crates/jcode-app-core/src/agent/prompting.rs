use super::Agent;
use crate::logging;
use crate::message::{Message, ToolDefinition};

/// Render one provider-visible message as readable text for the request dump.
///
/// Text blocks are emitted verbatim (this is what cache matching sees). Non-text
/// blocks are represented by a compact marker plus their salient payload, so a
/// divergence caused by reasoning/tool/image content is still locatable without
/// dumping binary or base64 bodies.
fn render_message_for_dump(message: &Message) -> String {
    use jcode_message_types::ContentBlock;

    let mut out = String::new();
    for (i, block) in message.content.iter().enumerate() {
        if i > 0 {
            out.push('\n');
        }
        match block {
            ContentBlock::Text { text, .. } => out.push_str(text),
            ContentBlock::Reasoning { text } => {
                out.push_str(&format!("<<reasoning {} chars>>{}", text.len(), text));
            }
            ContentBlock::ReasoningTrace { text } => {
                out.push_str(&format!("<<reasoning_trace {} chars>>", text.len()));
            }
            ContentBlock::AnthropicThinking { thinking, .. } => {
                out.push_str(&format!("<<anthropic_thinking {} chars>>", thinking.len()));
            }
            other => {
                // Tool calls/results, images, and future variants: marker plus
                // debug rendering, truncated so base64 payloads stay legible.
                let dbg = format!("{other:?}");
                let shown = dbg.chars().take(500).collect::<String>();
                out.push_str(&format!("<<non_text_block {} chars>>{}", dbg.len(), shown));
            }
        }
    }
    out
}

impl Agent {
    pub(super) fn log_prompt_prefix_accounting(
        &self,
        split: &crate::prompt::SplitSystemPrompt,
        tools: &[ToolDefinition],
    ) {
        let system_tokens = split.estimated_tokens();
        let tool_tokens = ToolDefinition::aggregate_prompt_token_estimate(tools);
        let prefix_tokens = system_tokens + tool_tokens;
        logging::info(&format!(
            "Prompt prefix estimate: total={} tokens (system={} tools={})",
            prefix_tokens, system_tokens, tool_tokens
        ));
    }

    /// Dump the exact rendered request payload that is about to be sent.
    ///
    /// This is the ground truth for prompt-prefix cache behavior. Prefix caching
    /// matches on the provider-visible bytes, so `log_prompt_prefix_accounting`
    /// (token counts) cannot answer "where did two requests diverge?" — only the
    /// rendered text can. See SPR-0010.
    ///
    /// Emits, in wire order: the static system prompt, the dynamic system
    /// prompt, the tool schemas, then each leading message with its role and
    /// rendered text. Each section is length-annotated so a divergence point can
    /// be located by inspection, and each carries a stable marker so the output
    /// can be extracted from the log with grep.
    ///
    /// Gated on `JCODE_TRACE` (via `logging::debug`), the existing debug switch.
    /// No new config surface: `JCODE_TRACE=1` already enables debug logging, and
    /// the payload contains repo context, so this must not be on by default.
    ///
    /// Extract with:
    /// `grep -A2 'REQUEST PAYLOAD DUMP' ~/.jcode/logs/jcode-$(date +%F).log`
    pub(super) fn dump_request_prefix(
        &self,
        split: &crate::prompt::SplitSystemPrompt,
        tools: &[ToolDefinition],
        messages: &[Message],
    ) {
        if std::env::var("JCODE_TRACE").is_err() {
            return;
        }

        // The prefix is what cache matching depends on, so the leading messages
        // are the ones that matter; the remainder is summarized by count.
        const DUMP_MESSAGE_LIMIT: usize = 8;

        logging::debug(&format!(
            "=== REQUEST PAYLOAD DUMP BEGIN session={} model={} messages={} tools={} ===",
            self.session.id,
            self.provider.model(),
            messages.len(),
            tools.len()
        ));

        // --- System prompt (static then dynamic, the cacheable/dynamic split) ---
        logging::debug(&format!(
            "--- SYSTEM STATIC ({} chars) ---\n{}",
            split.static_part.len(),
            split.static_part
        ));
        logging::debug(&format!(
            "--- SYSTEM DYNAMIC ({} chars) ---\n{}",
            split.dynamic_part.len(),
            split.dynamic_part
        ));

        // --- Tool schemas: the other half of the cacheable prefix ---
        let tool_names: Vec<&str> = tools.iter().map(|t| t.name.as_str()).collect();
        let tool_fingerprint = tools
            .iter()
            .map(|t| format!("{}:{}", t.name, t.description.len()))
            .collect::<Vec<_>>()
            .join(",");
        logging::debug(&format!(
            "--- TOOLS ({} defined: {}) ---\nfingerprint(name:desc_len)={}",
            tools.len(),
            tool_names.join(", "),
            tool_fingerprint
        ));

        // --- Provider-visible messages, in wire order ---
        let shown = messages.len().min(DUMP_MESSAGE_LIMIT);
        for (idx, message) in messages.iter().take(shown).enumerate() {
            let rendered = render_message_for_dump(message);
            logging::debug(&format!(
                "--- MESSAGE[{}] role={:?} len={} ---\n{}",
                idx,
                message.role,
                rendered.len(),
                rendered
            ));
        }
        if messages.len() > shown {
            logging::debug(&format!(
                "--- MESSAGES[{}..{}] elided ({} further messages not shown) ---",
                shown,
                messages.len(),
                messages.len() - shown
            ));
        }

        logging::debug(&format!(
            "=== REQUEST PAYLOAD DUMP END session={} ===",
            self.session.id
        ));
    }

    pub(super) fn build_memory_prompt_nonblocking_shared(
        &self,
        messages: std::sync::Arc<[Message]>,
        _memory_event_tx: Option<crate::memory::MemoryEventSink>,
    ) -> Option<crate::memory::PendingMemory> {
        if !self.memory_enabled {
            return None;
        }

        let session_id = &self.session.id;

        let fresh_user_turn = crate::message::ends_with_fresh_user_turn(&messages);
        let pending = if fresh_user_turn {
            crate::memory::take_pending_memory(session_id)
        } else {
            None
        };

        // Use the persistent memory-agent pipeline as the single source of truth.
        // Running both this and the legacy MemoryManager background retrieval path
        // can prepare overlapping pending prompts for the same turn, which makes
        // memory injection feel overly aggressive.
        // Relevance results are consumed only at the start of a fresh user turn.
        // Enqueuing again after every tool result runs the local embedding model
        // for each provider continuation without creating an additional injection
        // opportunity. One update per user turn keeps memory current while avoiding
        // redundant 512-token inference during tool-heavy agent loops.
        if fresh_user_turn {
            crate::memory_agent::update_context_sync_with_dir(
                session_id,
                messages,
                self.session.working_dir.clone(),
            );
        }

        pending
    }

    fn append_current_turn_system_reminder(&self, split: &mut crate::prompt::SplitSystemPrompt) {
        let Some(reminder) = self
            .current_turn_system_reminder
            .as_ref()
            .map(|value| value.trim())
            .filter(|value| !value.is_empty())
        else {
            return;
        };

        if !split.dynamic_part.is_empty() {
            split.dynamic_part.push_str("\n\n");
        }
        split.dynamic_part.push_str("# System Reminder\n\n");
        split.dynamic_part.push_str(reminder);
    }

    /// Build split system prompt for better caching
    /// Returns static (cacheable) and dynamic (not cached) parts separately
    pub(super) fn build_system_prompt_split(
        &self,
        memory_prompt: Option<&str>,
    ) -> crate::prompt::SplitSystemPrompt {
        if let Some(ref override_prompt) = self.system_prompt_override {
            return crate::prompt::SplitSystemPrompt {
                static_part: override_prompt.clone(),
                dynamic_part: String::new(),
            };
        }

        let skills = self.current_skills_snapshot();
        let skill_prompt = self
            .active_skill
            .as_ref()
            .and_then(|name| skills.get(name).map(|skill| skill.get_prompt().to_string()));

        let available_skills: Vec<crate::prompt::SkillInfo> = self
            .current_skills_snapshot()
            .list()
            .iter()
            .map(|skill| crate::prompt::SkillInfo {
                name: skill.name.clone(),
                description: skill.description.clone(),
            })
            .collect();

        let working_dir = self
            .session
            .working_dir
            .as_ref()
            .map(std::path::PathBuf::from);

        let (mut split, _context_info) = crate::prompt::build_system_prompt_split_with_agents_md(
            skill_prompt.as_deref(),
            &available_skills,
            self.session.is_canary,
            memory_prompt,
            working_dir.as_deref(),
            self.agents_md_snapshot.clone(),
        );

        self.append_current_turn_system_reminder(&mut split);
        crate::prompt::append_swarm_effort_directive(
            &mut split,
            self.provider.reasoning_effort().as_deref(),
        );

        split
    }

    /// Non-blocking memory prompt - takes pending result and spawns check for next turn
    #[cfg(test)]
    pub(super) fn build_memory_prompt_nonblocking(
        &self,
        messages: &[Message],
        _memory_event_tx: Option<crate::memory::MemoryEventSink>,
    ) -> Option<crate::memory::PendingMemory> {
        self.build_memory_prompt_nonblocking_shared(messages.to_vec().into(), _memory_event_tx)
    }
}
