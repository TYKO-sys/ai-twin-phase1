// AI Twin Wizard — Client-side logic

let currentStep = 1;

function showStep(stepNum) {
    // Hide all steps
    document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
    // Show the target step
    document.getElementById(`panel-${stepNum}`).classList.add('active');

    // Update progress bar
    document.querySelectorAll('.progress-step').forEach((el, i) => {
        el.classList.remove('active', 'done');
        if (i + 1 < stepNum) {
            el.classList.add('done');
        } else if (i + 1 === stepNum) {
            el.classList.add('active');
        }
    });

    currentStep = stepNum;

    // If it's the review step, populate the review
    if (stepNum === 4) {
        populateReview();
    }

    // Scroll to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function nextStep(current) {
    // Validate current step before proceeding
    if (current === 1) {
        const token = document.getElementById('telegram_token').value.trim();
        if (!token) {
            showError('Please paste your Telegram bot token first.');
            return;
        }
        if (!token.includes(':') || token.length < 20) {
            showError('That doesn\'t look like a valid bot token. It should look like: 123456789:AAH-xxxxx...');
            return;
        }
    }

    if (current === 2) {
        const userId = document.getElementById('user_id').value.trim();
        if (!userId) {
            showError('Please paste your Telegram user ID first.');
            return;
        }
        if (!/^\d+$/.test(userId)) {
            showError('Your user ID should be numbers only (no letters or symbols).');
            return;
        }
    }

    if (current === 3) {
        const orKey = document.getElementById('openrouter_key').value.trim();
        const deepseekKey = document.getElementById('deepseek_key').value.trim();
        const zaiKey = document.getElementById('zai_key').value.trim();
        const geminiKey = document.getElementById('gemini_key').value.trim();
        if (!orKey && !deepseekKey && !zaiKey && !geminiKey) {
            showError('You need at least one AI API key. Add as many as you can for maximum reliability.');
            return;
        }
    }

    hideError();
    showStep(current + 1);
}

function prevStep(current) {
    hideError();
    showStep(current - 1);
}

function populateReview() {
    const token = document.getElementById('telegram_token').value.trim();
    const userId = document.getElementById('user_id').value.trim();
    const orKey = document.getElementById('openrouter_key').value.trim();
    const deepseekKey = document.getElementById('deepseek_key').value.trim();
    const zaiKey = document.getElementById('zai_key').value.trim();
    const geminiKey = document.getElementById('gemini_key').value.trim();

    // Mask tokens for display (show first 10 and last 4 chars)
    document.getElementById('review_token').textContent = maskValue(token);
    document.getElementById('review_userid').textContent = userId;
    document.getElementById('review_or').textContent = orKey ? maskValue(orKey) : '(not set)';
    document.getElementById('review_deepseek').textContent = deepseekKey ? maskValue(deepseekKey) : '(not set)';
    document.getElementById('review_zai').textContent = zaiKey ? maskValue(zaiKey) : '(not set)';
    document.getElementById('review_gemini').textContent = geminiKey ? maskValue(geminiKey) : '(not set)';
}

function maskValue(value) {
    if (!value) return '(not set)';
    if (value.length <= 14) return value;
    return value.substring(0, 10) + '...' + value.substring(value.length - 4);
}

function showError(message) {
    const errorEl = document.getElementById('error-message');
    errorEl.textContent = message;
    errorEl.classList.add('show');
}

function hideError() {
    const errorEl = document.getElementById('error-message');
    errorEl.classList.remove('show');
}

function submitForm() {
    const token = document.getElementById('telegram_token').value.trim();
    const userId = document.getElementById('user_id').value.trim();
    const orKey = document.getElementById('openrouter_key').value.trim();
    const deepseekKey = document.getElementById('deepseek_key').value.trim();
    const zaiKey = document.getElementById('zai_key').value.trim();
    const geminiKey = document.getElementById('gemini_key').value.trim();

    // Final validation
    if (!token || !userId) {
        showError('Missing required fields. Go back and fill them in.');
        return;
    }

    if (!orKey && !deepseekKey && !zaiKey && !geminiKey) {
        showError('You need at least one AI API key.');
        return;
    }

    // Disable button and show loading
    const submitBtn = document.querySelector('.btn-submit');
    submitBtn.textContent = 'Saving...';
    submitBtn.disabled = true;

    // Prepare data
    const formData = new URLSearchParams();
    formData.append('telegram_token', token);
    formData.append('user_id', userId);
    formData.append('openrouter_key', orKey);
    formData.append('deepseek_key', deepseekKey);
    formData.append('zai_key', zaiKey);
    formData.append('gemini_key', geminiKey);

    // Optional SMTP fields (native email — no n8n needed)
    const smtpHost = document.getElementById('smtp_host') ? document.getElementById('smtp_host').value.trim() : '';
    const smtpPort = document.getElementById('smtp_port') ? document.getElementById('smtp_port').value.trim() : '';
    const smtpUser = document.getElementById('smtp_user') ? document.getElementById('smtp_user').value.trim() : '';
    const smtpPass = document.getElementById('smtp_pass') ? document.getElementById('smtp_pass').value.trim() : '';
    const smtpFrom = document.getElementById('smtp_from') ? document.getElementById('smtp_from').value.trim() : '';
    if (smtpHost) formData.append('smtp_host', smtpHost);
    if (smtpPort) formData.append('smtp_port', smtpPort);
    if (smtpUser) formData.append('smtp_user', smtpUser);
    if (smtpPass) formData.append('smtp_pass', smtpPass);
    if (smtpFrom) formData.append('smtp_from', smtpFrom);

    // Submit to server
    fetch('/submit', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData.toString(),
    })
    .then(response => response.json())
    .then(data => {
        if (data.errors) {
            showError(data.errors.join('. '));
            submitBtn.textContent = 'Finish Setup ✓';
            submitBtn.disabled = false;
        } else if (data.success) {
            // Show success panel
            document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
            document.getElementById('panel-success').classList.add('active');

            // Update all progress steps to done
            document.querySelectorAll('.progress-step').forEach(el => {
                el.classList.remove('active');
                el.classList.add('done');
            });
        }
    })
    .catch(error => {
        showError('Connection error. Make sure the wizard is still running.');
        submitBtn.textContent = 'Finish Setup ✓';
        submitBtn.disabled = false;
    });
}
