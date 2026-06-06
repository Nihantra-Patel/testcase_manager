import { createApp } from 'vue'
import {
  Button,
  Badge,
  Dialog,
  FeatherIcon,
  FormControl,
  Select,
  Tooltip,
  frappeRequest,
  setConfig,
  resourcesPlugin,
} from 'frappe-ui'
import router from './router'
import App from './App.vue'
import 'frappe-ui/style.css'
import './index.css'
import { initSocket } from './socket'

setConfig('resourceFetcher', frappeRequest)

const app = createApp(App)
app.use(resourcesPlugin)
app.use(router)

const globalComponents = { Button, Badge, Dialog, FeatherIcon, FormControl, Select, Tooltip }
for (const key in globalComponents) {
  app.component(key, globalComponents[key])
}

const socket = initSocket()
app.config.globalProperties.$socket = socket
app.provide('$socket', socket)

app.mount('#app')
