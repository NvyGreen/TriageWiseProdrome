import { BrowserRouter, Routes, Route } from 'react-router-dom'

import AppLayout from './layouts/AppLayout'
import PatientIntake from './pages/PatientIntake'


function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route element={<AppLayout />}>
                    <Route path='/' element={<PatientIntake />} />
                </Route>
            </Routes>
        </BrowserRouter>
    )
}

export default App
