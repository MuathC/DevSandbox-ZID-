// ============================================================
// AWS Personalize Tracking Snippets for Zid Stores
// ============================================================

// 1. PURCHASE TRACKING SNIPPET
// Add this to your order confirmation/thank you page
(function() {
    // Get order details from your page (adjust selectors as needed)
    const orderData = window.orderData || {}; // You'll need to populate this
    const productId = orderData.product_id || document.querySelector('[data-product-id]')?.dataset.productId;
    
    if (!productId) {
        console.warn('My Rec App: No product ID found for purchase tracking');
        return;
    }
    
    fetch('https://asnb-app.duckdns.org/track/purchase', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            store_id: '{{store.id}}',
            user_id: window.customer ? window.customer.id : null,
            session_id: localStorage.getItem('myAppSessionId') || 'session-' + Date.now(),
            item_id: productId
        })
    })
    .then(response => response.json())
    .then(data => {
        console.log('My Rec App: Purchase tracked successfully', data);
    })
    .catch(err => {
        console.error('My Rec App (Purchase Tracking Error):', err);
    });
})();


// 2. PRODUCT VIEW TRACKING SNIPPET
// Add this to your product detail page
(function() {
    // Get product ID from page (adjust selector as needed)
    const productId = document.querySelector('[data-product-id]')?.dataset.productId || 
                      window.productData?.id ||
                      new URLSearchParams(window.location.search).get('product_id');
    
    if (!productId) {
        console.warn('My Rec App: No product ID found for view tracking');
        return;
    }
    
    // Initialize session ID if not exists
    if (!localStorage.getItem('myAppSessionId')) {
        localStorage.setItem('myAppSessionId', 'session-' + Date.now());
    }
    
    fetch('https://asnb-app.duckdns.org/track/view', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            store_id: '{{store.id}}',
            user_id: window.customer ? window.customer.id : null,
            session_id: localStorage.getItem('myAppSessionId'),
            item_id: productId
        })
    })
    .then(response => response.json())
    .then(data => {
        console.log('My Rec App: View tracked successfully', data);
    })
    .catch(err => {
        console.error('My Rec App (View Tracking Error):', err);
    });
})();


// 3. ADD TO CART TRACKING SNIPPET
// Add this to your "Add to Cart" button click handler
(function() {
    // Get product ID from the add-to-cart button or form
    const productId = document.querySelector('[data-product-id]')?.dataset.productId ||
                      document.querySelector('form[action*="cart"] [name="product_id"]')?.value ||
                      window.productData?.id;
    
    if (!productId) {
        console.warn('My Rec App: No product ID found for cart tracking');
        return;
    }
    
    // Initialize session ID if not exists
    if (!localStorage.getItem('myAppSessionId')) {
        localStorage.setItem('myAppSessionId', 'session-' + Date.now());
    }
    
    fetch('https://asnb-app.duckdns.org/track/cart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            store_id: '{{store.id}}',
            user_id: window.customer ? window.customer.id : null,
            session_id: localStorage.getItem('myAppSessionId'),
            item_id: productId
        })
    })
    .then(response => response.json())
    .then(data => {
        console.log('My Rec App: Add to cart tracked successfully', data);
    })
    .catch(err => {
        console.error('My Rec App (Cart Tracking Error):', err);
    });
})();
