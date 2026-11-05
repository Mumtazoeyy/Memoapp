document.addEventListener('DOMContentLoaded', function () {
    const modeSelect = document.getElementById('id_import_mode');

    const nameRow = document.querySelector('.field-name');
    const bulkRow = document.querySelector('.field-bulk_tags');

    if (!modeSelect || !nameRow || !bulkRow) return;

    function updateMode() {
        const isBulk = modeSelect.value === 'bulk';

        nameRow.style.display = isBulk ? 'none' : '';
        bulkRow.style.display = isBulk ? '' : 'none';
    }

    modeSelect.addEventListener('change', updateMode);

    updateMode();
});