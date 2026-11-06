<template><span aria-hidden="true" style="display:none"></span></template>
<script>
module.exports={mounted(){this.$nextTick(()=>{const pane=this.$el.closest('.lab-main');if(pane)pane.scrollTop=0;});}};
</script>
