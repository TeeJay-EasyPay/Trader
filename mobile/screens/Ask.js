// Ask AI Trader: the founder's own screen as of the 2026-08-24 simplification.
//
// It used to sit at the bottom of Learning, below a wall of strategy-lab evidence the
// Founder had to scroll past to reach it. Learning's own numbers duplicated the Trade
// Scorecard on the Executive Briefing, so the screen was cut and the one genuinely unique
// line (the latest lesson) moved onto the Scorecard. What remains here is the part that was
// actually used: asking a plain-English question and getting a plain-English answer.

'use strict';

const React = require('react');
const { useState } = React;
const { Text, TextInput, View } = require('react-native');
const { styles } = require('../styles');
const { Section, Metric, Button } = require('../components/shared');
const { withTimeout, normalizeChatText, chatMessageText, chatTurnsNewestFirst } = require('../lib/chat');


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
    // 2026-08-24: was 25000, against a backend that answered a real question in 23.5s
    // once its own timeouts were fixed -- 1.5s of margin, so a slightly heavier
    // question gave the Founder "the request timed out" for an answer the backend had
    // actually produced. Ask is not the 1-2s dashboard refresh the shared client is
    // tuned for: it gathers evidence and calls OpenAI. The backend works to a 50s
    // budget and always returns something by then (a real answer, or the stored
    // evidence summary), so wait for that rather than hanging up just before it lands.
    const timeoutMs = 55000;
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

module.exports = { AskAiTrader };
