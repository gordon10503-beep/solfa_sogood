const invite = new URLSearchParams(location.hash.slice(1)).get("invite");
const form = document.querySelector("form"), button=form.querySelector("button");
if(invite){
  document.querySelector("#heading").textContent="Create your account";
  document.querySelector("#intro").textContent="Choose a username and a password of at least 10 characters for your own score library.";
  form.elements.password.autocomplete="new-password"; form.elements.password.minLength=10;
  button.textContent="Join workspace";
}
form.onsubmit=async event=>{
  event.preventDefault();button.disabled=true;
  try{
    const response=await fetch(invite?"/api/register":"/api/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...Object.fromEntries(new FormData(form)),invite})});
    if(!response.ok)throw new Error((await response.json()).error);
    location.replace("/");
  }catch(error){document.querySelector("#message").textContent=error.message;button.disabled=false;}
};
