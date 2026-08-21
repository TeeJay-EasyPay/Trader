// Learning screen: strategy lab evidence summary plus the Ask AI Trader chat.
// Extracted from App.js as part of AT-ED-011 Phase 2 (mobile modularisation).

'use strict';

const React = require('react');
const { useState } = React;
const { Text, TextInput, View } = require('react-native');
const { styles } = require('../styles');
const { Section, CollapsibleSection, Metric, TextBlock, Button } = require('../components/shared');
const { notAvailable } = require('../lib/notAvailable');
const { formatPercent } = require('../lib/datetime');
const { formatList } = require('../lib/lists');
const { formatJsonText } = require('../lib/json');
const { moneyOrText } = require('../lib/money');
const { yesNo } = require('../lib/founderPresentation');
const { withTimeout, normalizeChatText, chatMessageText, chatTurnsNewestFirst } = require('../lib/chat');
const { cioLearningNarrative } = require('../lib/cio');

function AskAiTrader({ messages, setMessages, request }) {
  const [question, setQuestion] = useState('');
  const [askLoading, setAskLoading] = useState(false);
  const [askStatus, setAskStatus] = useState('Ready');
  const ask = async (text) => {
    const finalQuestion = String(text || question || '').trim();
    if (!finalQuestion || askLoading) {
      return;
    }
    setQuestion('');
    setMessages((prev) => [...prev, { role: 'user', text: normalizeChatText(finalQuestion) }]);
    setAskLoading(true);
    setAskStatus('Thinking...');
    const controller = new AbortController();
    const timeoutMs = 25000;
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const result = await withTimeout(
        request('/ask-ai-trader', {
          method: 'POST',
          body: JSON.stringify({ question: finalQuestion }),
          signal: controller.signal,
        }),
        timeoutMs + 2000
      );
      const answerText = normalizeChatText(result.answer);
      const note = result.note ? `\n\n${normalizeChatText(result.note)}` : '';
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(`${answerText}${note}`) }]);
      setAskStatus(`Answered using ${result.model || 'local evidence'}.`);
    } catch (error) {
      // AT-ED-013 Section 12: never surface a raw exception/stack-trace string to the
      // Founder - only the timeout case gets a specific explanation (it has a genuine,
      // actionable business meaning: the backend is slow to wake up); anything else is
      // reported honestly but in plain English, with no exception text attached.
      const message = String(error.message || error);
      const friendly = message.includes('AbortError') || message.includes('aborted') || message.includes('timed out')
        ? 'The Ask request timed out before the backend replied. Render or OpenAI may still be waking up. Try again in a moment, or ask a shorter question.'
        : 'I could not answer that yet - something went wrong reaching AI Trader. Please try again in a moment.';
      setMessages((prev) => [...prev, { role: 'assistant', text: normalizeChatText(friendly) }]);
      setAskStatus('Ask failed or timed out.');
    } finally {
      clearTimeout(timeout);
      setAskLoading(false);
    }
  };
  const suggestions = [
    'Am I up or down today, and why?',
    'What open positions do I have?',
    'Which recent trades made or lost money?',
    'What has AI Trader learned today?',
    'Is AI Trader getting better at trading?',
  ];
  return (
    <View>
      <Section title="Ask AI Trader">
        <Text style={styles.bodyText}>
          Ask for a plain-English explanation of AI Trader data. This chat is read-only and cannot place trades, approve trades, enable auto trading, or change guardrails.
        </Text>
        <Metric label="Ask Status" value={askStatus} />
        <View style={styles.buttonGrid}>
          {suggestions.map((item) => (
            <Button key={item} label={item} tone="neutral" onPress={() => ask(item)} disabled={askLoading} />
          ))}
        </View>
        <TextInput
          style={[styles.input, styles.multilineInput]}
          multiline
          placeholder="Ask AI Trader a question..."
          value={question}
          onChangeText={setQuestion}
        />
        <Button label={askLoading ? 'Thinking...' : 'Ask'} onPress={() => ask()} disabled={askLoading || !question.trim()} />
      </Section>
      <Section title="Conversation">
        {messages.length ? (
          chatTurnsNewestFirst(messages).map((turn, turnIndex) => (
            <View key={`turn-${turnIndex}`} style={styles.chatTurn}>
              {turn.map((item, messageIndex) => (
                <View key={`${item.role}-${turnIndex}-${messageIndex}`} style={[styles.chatBubble, item.role === 'user' ? styles.chatUser : styles.chatAssistant]}>
                  <Text style={styles.metricLabel}>{item.role === 'user' ? 'You' : 'AI Trader'}</Text>
                  <Text style={styles.bodyText} selectable>{chatMessageText(item.text)}</Text>
                </View>
              ))}
            </View>
          ))
        ) : (
          <Text style={styles.bodyText}>Ask me about balances, open positions, trades, reports, recommendations, or what AI Trader learned.</Text>
        )}
      </Section>
    </View>
  );
}

function LearningStrategyLab({ status, dailyLearning, messages, setMessages, request }) {
  const lab = status?.founder_experience?.learning_lab || {};
  const strategyRows = lab.strategy_rankings || [];
  const signalRows = lab.signal_rankings || [];
  const summary = dailyLearning?.evidence_summary || {
    completedTradesReviewed: dailyLearning?.trade_outcomes?.closed_trades || 0,
    strategiesEvaluated: 0,
    latestLesson: null,
    hasEnoughEvidence: false,
    missingEvidence: 'Learning evidence has not loaded yet.',
  };
  const hasInstitutionalTestData = Boolean(lab.backtest_results || lab.walk_forward_results || lab.committee_performance);

  return (
    <View>
      <View style={styles.summaryCard}>
        {/* AT-ED-013 Section 9: the Learning screen framed as a CIO quarterly performance
            review - a real narrative built from the same evidence_summary fields already
            computed below, via lib/cio.js's cioLearningNarrative. */}
        <Text style={styles.summaryReason}>
          {cioLearningNarrative({
            completedTradesReviewed: summary.completedTradesReviewed,
            latestLesson: summary.latestLesson,
            hasEnoughEvidence: summary.hasEnoughEvidence,
            missingEvidence: summary.missingEvidence,
          })}
        </Text>
        <Metric label="Completed Trades Reviewed" value={summary.completedTradesReviewed} />
        <Metric label="Strategies Evaluated" value={summary.strategiesEvaluated} />
        <Metric label="Latest Lesson" value={summary.latestLesson || 'No lesson recorded yet.'} />
        <Metric label="Latest Strategy-Change Proposal" value={summary.latestProposal || 'AI Trader has not proposed a strategy change yet.'} />
        <Metric label="Proposal Approved" value={summary.proposalApproved === null ? 'No proposal to approve yet' : yesNo(summary.proposalApproved)} />
        {!summary.hasEnoughEvidence ? (
          <View style={styles.compactRow}>
            <Text style={styles.cardTitle}>Why learning has not progressed further</Text>
            <Text style={styles.bodyText}>{summary.missingEvidence}</Text>
          </View>
        ) : (
          <TextBlock label="Evidence Note" value={summary.missingEvidence} />
        )}
      </View>

      {/* APP SIMPLIFICATION (2026-08-21): salvaged from the now-deleted Market screen's
          "Today's Learning, In Brief" card. It carried the raw backend `dailyLearning.summary`
          sentence, which is distinct from (and not otherwise shown by) the cioLearningNarrative
          composed above from evidence_summary - worth keeping, not worth a whole screen. The
          original card's pointer text ("See the Learning tab...") is dropped since this is now
          that tab. */}
      {dailyLearning?.summary ? (
        <Section title="Today's Learning, In Brief">
          <Text style={styles.bodyText}>{dailyLearning.summary}</Text>
        </Section>
      ) : null}

      {/* 2026-08-18 Founder request: labels made explicit after the 2026-08-17 finding that
          Alpaca legacy positions (never proposed by the AI) were being counted as "closed
          trades" here, misrepresenting the AI's own judgment. */}
      <CollapsibleSection title="Trade Outcomes" subtitle="Win rate and realized P&L from trades the AI itself decided and executed - excludes any pre-existing or manually-placed position.">
        <Metric label="AI-Decided Closed Trades" value={dailyLearning?.trade_outcomes?.closed_trades} />
        <Metric label="Win Rate (AI-decided trades)" value={formatPercent(dailyLearning?.trade_outcomes?.win_rate)} />
        <Metric label="Total Realized P&L (AI-decided trades)" value={moneyOrText(dailyLearning?.trade_outcomes?.total_profit_loss)} />
        <TextBlock label="Lessons Learned" value={formatList(dailyLearning?.trade_lessons)} />
        <TextBlock label="Recommendations for Founder" value={formatList(dailyLearning?.recommendations_for_founder)} />
      </CollapsibleSection>

      {(strategyRows.length || signalRows.length || hasInstitutionalTestData) ? (
        <CollapsibleSection title="Strategy and Signal Rankings" subtitle="Institutional-grade backtest and ranking evidence, where available.">
          {strategyRows.map((item, index) => (
            <View key={`${item.strategy_id || item.strategy_name}-${index}`} style={styles.compactRow}>
              <Text style={styles.cardTitle}>{notAvailable(item.strategy_name || item.strategy_id)}</Text>
              <Metric label="Sample Size" value={item.sample_size} />
              <Metric label="Win Rate" value={formatPercent(item.win_rate)} />
              <Metric label="Expectancy" value={item.expectancy_r !== undefined ? `${Number(item.expectancy_r).toFixed(2)}R` : null} />
              <Metric label="Recommendation" value={item.recommendation} />
            </View>
          ))}
          {signalRows.map((item, index) => (
            <View key={`${item.signal_name || item.signal}-${index}`} style={styles.compactRow}>
              <Text style={styles.cardTitle}>{notAvailable(item.signal_name || item.signal)}</Text>
              <Metric label="Score" value={formatPercent(item.score)} />
              <Metric label="Weight" value={formatPercent(item.weight)} />
              <Metric label="Direction" value={item.direction} />
            </View>
          ))}
          {hasInstitutionalTestData ? (
            <>
              <TextBlock label="Backtest Results" value={formatJsonText(lab.backtest_results)} />
              <TextBlock label="Walk-forward Results" value={formatJsonText(lab.walk_forward_results)} />
              <TextBlock label="Committee Performance" value={formatJsonText(lab.committee_performance)} />
            </>
          ) : null}
        </CollapsibleSection>
      ) : null}

      <AskAiTrader messages={messages} setMessages={setMessages} request={request} />
    </View>
  );
}

module.exports = { LearningStrategyLab };
