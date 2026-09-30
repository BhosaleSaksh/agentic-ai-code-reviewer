// Pure JavaScript utility functions without security violations.

function calculateTotal(items) {
    return items.reduce((acc, item) => acc + item.price, 0);
}

function formatCurrency(amount) {
    return '$' + Number(amount).toFixed(2);
}

module.exports = { calculateTotal, formatCurrency };
