function formatList(items) {
  if (!items || !items.length) {
    return null;
  }
  if (typeof items === 'string') {
    return items;
  }
  if (!Array.isArray(items)) {
    return String(items);
  }
  return items.map((item) => `- ${item}`).join('\n');
}

function formatListInline(items) {
  if (!items || !items.length) {
    return null;
  }
  if (typeof items === 'string') {
    return items;
  }
  if (!Array.isArray(items)) {
    return String(items);
  }
  return items.join(', ');
}

module.exports = {
  formatList,
  formatListInline,
};
