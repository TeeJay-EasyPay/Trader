'use strict';

// What a question cost, in money the Founder actually thinks in.
//
// 2026-09-07: his first $6 of Anthropic credit went overnight, and the only place he could
// find out where was Anthropic's billing page the following morning. Cost that is invisible
// until the next day is cost nobody can steer.
//
// Lives in lib/ rather than in the screen so it can be exercised by node -- the same reason
// spokenReply.js and chatBubbles.js are here. A screen with JSX in it cannot be required.

// Rough, and deliberately not fetched. A live FX call to put a penny figure on screen would
// cost more attention than the number is worth; this is right to well within the rounding.
const USD_TO_GBP = 0.79;

function formatPence(usd) {
  const amount = Number(usd);
  if (!Number.isFinite(amount) || amount <= 0) return '';
  const pence = amount * USD_TO_GBP * 100;
  // Under a pound, pence read better: "22.9p" lands where "£0.23" does not. Below a tenth of
  // a penny say "<0.1p" rather than "0.0p", which reads as free when it is not.
  if (pence < 0.1) return '<0.1p';
  if (pence < 100) return `${pence.toFixed(1)}p`;
  return `£${(pence / 100).toFixed(2)}`;
}

module.exports = { formatPence, USD_TO_GBP };
